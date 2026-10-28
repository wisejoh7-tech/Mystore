import json
import hmac
import hashlib
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from web.models import User, Order, Expense
from web.banking.models import (
    BankAccountConnection,
    BankAccount,
    BankTransaction,
    BankStatement,
    BankCharge,
    ReconciliationRecord,
    BankingAuditLog
)
from web.banking.crypto import encrypt_secret, decrypt_secret
from web.banking.adapters import BankProviderRegistry, TransferNotAuthorizedError, MockBankProviderAdapter
from web.banking.services import (
    BankConnectionService,
    TransactionSyncService,
    StatementImportService,
    ReconciliationService,
    BankChargeService,
    AccountMonitoringService
)


class BankingIntegrationTests(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(username="tenant1", email="tenant1@example.com", password="password123")
        self.user2 = User.objects.create_user(username="tenant2", email="tenant2@example.com", password="password123")
        self.client1 = Client()
        self.client1.login(username="tenant1", password="password123")

    def test_crypto_encryption(self):
        token = "secret_access_token_xyz"
        encrypted = encrypt_secret(token)
        self.assertNotEqual(token, encrypted)
        decrypted = decrypt_secret(encrypted)
        self.assertEqual(token, decrypted)

    def test_bank_connection_flow_requires_provider_confirmation(self):
        # Step 1: Initiate connection (State must be PENDING, credentials must NOT be stored)
        init_res = BankConnectionService.initiate_connection(self.user1, "mock")
        conn_id = init_res['connection_id']

        conn = BankAccountConnection.objects.get(id=conn_id)
        self.assertEqual(conn.status, 'PENDING')
        self.assertIsNone(conn.encrypted_access_token)
        self.assertIsNone(conn.provider_confirmed_at)

        # Audit log created
        log = BankingAuditLog.objects.filter(user=self.user1, action='CONNECTION_REQUEST').first()
        self.assertIsNotNone(log)

        # Step 2: Confirm connection via provider token exchange
        conn_confirmed = BankConnectionService.confirm_connection(self.user1, conn_id, "mock_pub_token_999")
        self.assertEqual(conn_confirmed.status, 'CONNECTED')
        self.assertIsNotNone(conn_confirmed.provider_confirmed_at)
        self.assertIsNotNone(conn_confirmed.encrypted_access_token)
        self.assertEqual(decrypt_secret(conn_confirmed.encrypted_access_token), "mock_access_token_token_999")

        # Accounts should be linked and active
        accounts = BankAccount.objects.filter(connection=conn_confirmed)
        self.assertEqual(accounts.count(), 2)
        for acc in accounts:
            self.assertEqual(acc.status, 'ACTIVE')
            self.assertFalse(acc.is_transfers_enabled)  # Guardrail active

    def test_transaction_sync_idempotency(self):
        init_res = BankConnectionService.initiate_connection(self.user1, "mock")
        conn = BankConnectionService.confirm_connection(self.user1, init_res['connection_id'], "mock_pub_token_111")
        acc = BankAccount.objects.get(connection=conn, external_account_id="mock_acc_001")

        # First sync
        res1 = TransactionSyncService.sync_account_transactions(self.user1, acc)
        self.assertGreater(res1['created_transactions'], 0)
        initial_tx_count = BankTransaction.objects.filter(bank_account=acc).count()

        # Second sync with identical transactions (Idempotent check)
        res2 = TransactionSyncService.sync_account_transactions(self.user1, acc)
        self.assertEqual(res2['created_transactions'], 0)
        self.assertEqual(res2['updated_transactions'], initial_tx_count)
        self.assertEqual(BankTransaction.objects.filter(bank_account=acc).count(), initial_tx_count)

    def test_statement_import_idempotency(self):
        acc = BankAccount.objects.create(
            user=self.user1,
            bank_name="Test Bank",
            account_name="Main",
            account_number_mask="****1111"
        )
        now_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        csv_content = (
            f"date,amount,description,transaction_id\n"
            f"{now_str},50000.00,Client Direct Deposit,TX_CSV_001\n"
            f"{now_str},-150.00,Monthly Maintenance Fee,TX_CSV_002\n"
        )

        # First import
        stmt1 = StatementImportService.import_statement(self.user1, acc, csv_content, "statement.csv", "CSV")
        self.assertEqual(stmt1.status, 'COMPLETED')
        self.assertEqual(stmt1.imported_records, 2)

        # Duplicate import
        stmt2 = StatementImportService.import_statement(self.user1, acc, csv_content, "statement_copy.csv", "CSV")
        self.assertEqual(stmt2.status, 'COMPLETED')
        self.assertEqual(stmt2.imported_records, 0)
        self.assertEqual(BankTransaction.objects.filter(bank_account=acc).count(), 2)

    def test_auto_and_manual_reconciliation(self):
        acc = BankAccount.objects.create(
            user=self.user1,
            bank_name="Recon Bank",
            account_name="Ops",
            account_number_mask="****2222"
        )
        order = Order.objects.create(
            user=self.user1,
            items_json='[]',
            total=Decimal('45000.00'),
            complete=False,
            status='Pending'
        )
        expense = Expense.objects.create(
            description="Office Supplies",
            amount=Decimal('8500.00'),
            category="Utility"
        )

        # Inflow transaction matching Order total
        tx_in = BankTransaction.objects.create(
            user=self.user1,
            bank_account=acc,
            external_transaction_id="TX_RECON_IN",
            transaction_date=datetime.now(timezone.utc),
            amount=Decimal('45000.00'),
            description="Order payment deposit"
        )

        # Outflow transaction matching Expense total
        tx_out = BankTransaction.objects.create(
            user=self.user1,
            bank_account=acc,
            external_transaction_id="TX_RECON_OUT",
            transaction_date=datetime.now(timezone.utc),
            amount=Decimal('-8500.00'),
            description="Stationery Store Purchase"
        )

        reconciled_count = ReconciliationService.auto_reconcile_transactions(self.user1, acc)
        self.assertEqual(reconciled_count, 2)

        order.refresh_from_db()
        self.assertTrue(order.complete)
        self.assertEqual(order.status, 'Paid')

        rec_in = ReconciliationRecord.objects.get(bank_transaction=tx_in)
        self.assertEqual(rec_in.order, order)
        self.assertEqual(rec_in.status, 'RECONCILED')

        rec_out = ReconciliationRecord.objects.get(bank_transaction=tx_out)
        self.assertEqual(rec_out.expense, expense)

    def test_bank_charge_detection(self):
        acc = BankAccount.objects.create(
            user=self.user1,
            bank_name="Fee Bank",
            account_name="Checking",
            account_number_mask="****3333"
        )
        tx_charge = BankTransaction.objects.create(
            user=self.user1,
            bank_account=acc,
            external_transaction_id="TX_FEE_1",
            transaction_date=datetime.now(timezone.utc),
            amount=Decimal('-450.00'),
            description="SMS Alert Notification Fee",
            is_charge=True
        )

        recorded = BankChargeService.detect_and_record_charges(self.user1, acc)
        self.assertEqual(recorded, 1)

        charge = BankCharge.objects.get(bank_transaction=tx_charge)
        self.assertEqual(charge.amount, Decimal('450.00'))
        self.assertEqual(charge.charge_type, 'FEE')

    def test_transfer_guardrail_prevents_unauthorized_transfers(self):
        adapter = BankProviderRegistry.get_adapter("mock")
        with self.assertRaises(TransferNotAuthorizedError):
            adapter.initiate_transfer(
                access_token="valid_token",
                source_account_id="acc_123",
                destination_account_number="9988776655",
                amount=10000.00,
                is_explicitly_authorized=False
            )

        # Verify audit log records blocked attempt
        log = BankingAuditLog.objects.filter(action='TRANSFER_BLOCKED').first()

    def test_webhook_signature_verification(self):
        payload = json.dumps({"event": "account.updated", "account_id": "mock_acc_001"}).encode('utf-8')
        valid_sig = hmac.new(b"mock_webhook_secret", payload, hashlib.sha256).hexdigest()

        # Valid signature request
        response_valid = self.client.post(
            reverse('bank_webhook_handler', kwargs={'provider_name': 'mock'}),
            data=payload,
            content_type="application/json",
            HTTP_X_PROVIDER_SIGNATURE=valid_sig
        )
        self.assertEqual(response_valid.status_code, 200)

        # Invalid signature request
        response_invalid = self.client.post(
            reverse('bank_webhook_handler', kwargs={'provider_name': 'mock'}),
            data=payload,
            content_type="application/json",
            HTTP_X_PROVIDER_SIGNATURE="bad_signature"
        )
        self.assertEqual(response_invalid.status_code, 400)

    def test_tenant_isolation(self):
        # User 1 connection
        init1 = BankConnectionService.initiate_connection(self.user1, "mock")
        conn1 = BankConnectionService.confirm_connection(self.user1, init1['connection_id'], "mock_pub_u1")
        acc1 = BankAccount.objects.get(connection=conn1, external_account_id="mock_acc_001")

        # User 2 should NOT see User 1's accounts or dashboard summary
        client2 = Client()
        client2.login(username="tenant2", password="password123")
        summary2 = AccountMonitoringService.get_account_status_summary(self.user2)
        self.assertEqual(summary2['total_accounts'], 0)

        # User 2 attempting to sync User 1's account should fail or return 404
        response = client2.post(reverse('bank_sync_transactions', kwargs={'account_id': acc1.id}))
        self.assertEqual(response.status_code, 404)
