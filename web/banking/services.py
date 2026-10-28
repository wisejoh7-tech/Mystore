import csv
import io
import json
import hashlib
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Dict, List, Any, Optional, Tuple

from django.db import transaction
from django.utils import timezone as django_timezone
from django.core.exceptions import ValidationError

from web.models import Order, Expense, User
from .models import (
    BankAccountConnection,
    BankAccount,
    BankTransaction,
    BankStatement,
    BankCharge,
    ReconciliationRecord,
    BankingAuditLog
)
from .crypto import encrypt_secret, decrypt_secret
from .adapters import BankProviderRegistry, TransferNotAuthorizedError

logger = logging.getLogger(__name__)


class BankConnectionService:
    @staticmethod
    def initiate_connection(user: User, provider_name: str, redirect_url: Optional[str] = None) -> Dict[str, Any]:
        """
        Initiates bank connection flow. State is marked PENDING until provider explicitly confirms authorization.
        Online banking credentials are never stored.
        """
        adapter = BankProviderRegistry.get_adapter(provider_name)
        link_data = adapter.create_link_token(str(user.id), redirect_url)

        with transaction.atomic():
            connection = BankAccountConnection.objects.create(
                user=user,
                provider_name=provider_name,
                status='PENDING',
                raw_metadata={'link_token': link_data.get('link_token')}
            )

            BankingAuditLog.objects.create(
                user=user,
                action='CONNECTION_REQUEST',
                status='SUCCESS',
                details={
                    'connection_id': str(connection.id),
                    'provider': provider_name
                }
            )

        return {
            'connection_id': str(connection.id),
            'status': 'PENDING',
            'link_token': link_data.get('link_token'),
            'connect_url': link_data.get('connect_url')
        }

    @staticmethod
    def confirm_connection(user: User, connection_id: str, public_token: str) -> BankAccountConnection:
        """
        Exchanges provider public token. Updates connection status to CONNECTED ONLY after provider confirms authorization.
        """
        with transaction.atomic():
            connection = BankAccountConnection.objects.select_for_update().get(
                id=connection_id,
                user=user
            )

            adapter = BankProviderRegistry.get_adapter(connection.provider_name)
            exchange_res = adapter.exchange_public_token(public_token)

            if exchange_res.get('status') != 'CONNECTED':
                connection.status = 'ERROR'
                connection.error_details = "Provider failed to confirm active authorization."
                connection.save()
                BankingAuditLog.objects.create(
                    user=user,
                    action='CONNECTION_CONFIRMED',
                    status='FAILURE',
                    details={'connection_id': connection_id, 'reason': 'Provider rejected token exchange'}
                )
                raise ValueError("Provider did not confirm connection authorization.")

            # Store secrets securely using encryption
            connection.encrypted_access_token = encrypt_secret(exchange_res.get('access_token', ''))
            connection.external_connection_id = exchange_res.get('external_connection_id')
            connection.status = 'CONNECTED'
            connection.provider_confirmed_at = django_timezone.now()
            connection.last_synced_at = django_timezone.now()
            connection.raw_metadata.update(exchange_res)
            connection.save()

            # Sync accounts for this connection
            raw_accounts = adapter.fetch_accounts(exchange_res.get('access_token'))
            for acc in raw_accounts:
                BankAccount.objects.update_or_create(
                    user=user,
                    connection=connection,
                    external_account_id=acc.get('external_account_id'),
                    defaults={
                        'bank_name': acc.get('bank_name', connection.provider_name.capitalize()),
                        'account_name': acc.get('account_name', 'Bank Account'),
                        'account_number_mask': acc.get('account_number_mask', '****0000'),
                        'account_type': acc.get('account_type', 'CHECKING'),
                        'currency': acc.get('currency', 'NGN'),
                        'ledger_balance': Decimal(str(acc.get('ledger_balance', 0.0))),
                        'available_balance': Decimal(str(acc.get('available_balance', 0.0))),
                        'status': 'ACTIVE',
                        'is_transfers_enabled': False  # Guardrail: disabled by default
                    }
                )

            BankingAuditLog.objects.create(
                user=user,
                action='CONNECTION_CONFIRMED',
                status='SUCCESS',
                details={
                    'connection_id': connection_id,
                    'provider': connection.provider_name,
                    'accounts_synced': len(raw_accounts)
                }
            )

        return connection

    @staticmethod
    def disconnect_connection(user: User, connection_id: str) -> bool:
        """
        Revokes connection and safely purges encrypted tokens.
        """
        with transaction.atomic():
            connection = BankAccountConnection.objects.get(id=connection_id, user=user)
            connection.status = 'DISCONNECTED'
            connection.encrypted_access_token = None
            connection.encrypted_refresh_token = None
            connection.save()

            # Set associated bank accounts to inactive
            BankAccount.objects.filter(connection=connection).update(status='INACTIVE')

            BankingAuditLog.objects.create(
                user=user,
                action='CONNECTION_REVOKED',
                status='SUCCESS',
                details={'connection_id': connection_id}
            )
        return True


class TransactionSyncService:
    @staticmethod
    def sync_account_transactions(
        user: User,
        bank_account: BankAccount,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Synchronizes external provider transactions idempotently.
        """
        if not bank_account.connection or bank_account.connection.status != 'CONNECTED':
            raise ValueError("Bank account connection is not active or authorized.")

        connection = bank_account.connection
        access_token = decrypt_secret(connection.encrypted_access_token)
        adapter = BankProviderRegistry.get_adapter(connection.provider_name)

        BankingAuditLog.objects.create(
            user=user,
            action='SYNC_STARTED',
            status='SUCCESS',
            details={'account_id': str(bank_account.id)}
        )

        external_txs = adapter.fetch_transactions(access_token, start_date, end_date)
        created_count = 0
        updated_count = 0

        with transaction.atomic():
            for tx_data in external_txs:
                ext_tx_id = tx_data.get('external_transaction_id')
                if not ext_tx_id:
                    continue

                tx_date_str = tx_data.get('date')
                if isinstance(tx_date_str, str):
                    try:
                        tx_date = datetime.fromisoformat(tx_date_str)
                    except ValueError:
                        tx_date = django_timezone.now()
                else:
                    tx_date = tx_date_str or django_timezone.now()

                amt = Decimal(str(tx_data.get('amount', '0.00')))
                desc = tx_data.get('description', '')
                is_charge = tx_data.get('is_charge', False) or any(
                    kw in desc.lower() for kw in ['fee', 'charge', 'commission', 'vat', 'maintenance']
                )

                tx_obj, created = BankTransaction.objects.get_or_create(
                    bank_account=bank_account,
                    external_transaction_id=ext_tx_id,
                    defaults={
                        'user': user,
                        'transaction_date': tx_date,
                        'amount': amt,
                        'currency': tx_data.get('currency', bank_account.currency),
                        'description': desc,
                        'category': tx_data.get('category'),
                        'is_charge': is_charge,
                        'raw_metadata': tx_data
                    }
                )

                if created:
                    created_count += 1
                else:
                    tx_obj.amount = amt
                    tx_obj.description = desc
                    tx_obj.is_charge = is_charge
                    tx_obj.save()
                    updated_count += 1

            connection.last_synced_at = django_timezone.now()
            connection.save()

            BankingAuditLog.objects.create(
                user=user,
                action='SYNC_COMPLETED',
                status='SUCCESS',
                details={
                    'account_id': str(bank_account.id),
                    'created_transactions': created_count,
                    'updated_transactions': updated_count,
                }
            )

        # Automatically process charges & auto-reconcile
        BankChargeService.detect_and_record_charges(user, bank_account)
        ReconciliationService.auto_reconcile_transactions(user, bank_account)

        return {
            'account_id': str(bank_account.id),
            'created_transactions': created_count,
            'updated_transactions': updated_count,
            'total_synced': len(external_txs)
        }


class StatementImportService:
    @staticmethod
    def import_statement(
        user: User,
        bank_account: BankAccount,
        file_content: str,
        file_name: str,
        file_format: str = 'CSV'
    ) -> BankStatement:
        """
        Imports and parses statement content (CSV/JSON/OFX) into idempotent BankTransaction entries.
        """
        statement = BankStatement.objects.create(
            user=user,
            bank_account=bank_account,
            file_name=file_name,
            file_format=file_format.upper(),
            status='PROCESSING'
        )

        try:
            records = []
            if file_format.upper() == 'CSV':
                records = StatementImportService._parse_csv(file_content)
            elif file_format.upper() == 'JSON':
                records = json.loads(file_content)
            else:
                records = StatementImportService._parse_csv(file_content)

            statement.total_records = len(records)
            imported_count = 0

            with transaction.atomic():
                for rec in records:
                    date_val = rec.get('date') or rec.get('transaction_date')
                    if isinstance(date_val, str):
                        try:
                            tx_date = datetime.strptime(date_val, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                        except ValueError:
                            tx_date = django_timezone.now()
                    else:
                        tx_date = django_timezone.now()

                    amt = Decimal(str(rec.get('amount', '0.00')))
                    desc = rec.get('description', 'Imported Statement Line')

                    # Generate deterministic hash for idempotency if no external ID exists
                    raw_sig = f"{bank_account.id}_{tx_date.strftime('%Y%m%d')}_{amt}_{desc}"
                    ext_tx_id = rec.get('external_transaction_id') or f"stmt_{hashlib.md5(raw_sig.encode()).hexdigest()}"

                    is_charge = any(kw in desc.lower() for kw in ['fee', 'charge', 'commission', 'vat', 'maintenance'])

                    tx_obj, created = BankTransaction.objects.get_or_create(
                        bank_account=bank_account,
                        external_transaction_id=ext_tx_id,
                        defaults={
                            'user': user,
                            'transaction_date': tx_date,
                            'amount': amt,
                            'currency': bank_account.currency,
                            'description': desc,
                            'category': rec.get('category', 'STATEMENT_IMPORT'),
                            'is_charge': is_charge,
                            'raw_metadata': rec
                        }
                    )
                    if created:
                        imported_count += 1

                statement.imported_records = imported_count
                statement.status = 'COMPLETED'
                statement.save()

                BankingAuditLog.objects.create(
                    user=user,
                    action='STATEMENT_IMPORTED',
                    status='SUCCESS',
                    details={
                        'statement_id': str(statement.id),
                        'file_name': file_name,
                        'imported_records': imported_count
                    }
                )

            # Auto reconcile after statement import
            BankChargeService.detect_and_record_charges(user, bank_account)
            ReconciliationService.auto_reconcile_transactions(user, bank_account)

        except Exception as e:
            logger.error(f"Error importing bank statement: {e}")
            statement.status = 'FAILED'
            statement.error_message = str(e)
            statement.save()
            BankingAuditLog.objects.create(
                user=user,
                action='STATEMENT_IMPORTED',
                status='FAILURE',
                details={'statement_id': str(statement.id), 'error': str(e)}
            )

        return statement

    @staticmethod
    def _parse_csv(content: str) -> List[Dict[str, Any]]:
        results = []
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            normalized = {k.lower().strip(): v.strip() for k, v in row.items() if k}
            date_str = normalized.get('date') or normalized.get('transaction_date') or normalized.get('tx_date')
            amt_str = normalized.get('amount') or normalized.get('val') or '0.00'
            desc_str = normalized.get('description') or normalized.get('narration') or normalized.get('memo') or ''
            ext_id = normalized.get('transaction_id') or normalized.get('reference') or normalized.get('id')

            results.append({
                'date': date_str,
                'amount': amt_str,
                'description': desc_str,
                'external_transaction_id': ext_id
            })
        return results


class ReconciliationService:
    @staticmethod
    def auto_reconcile_transactions(user: User, bank_account: BankAccount) -> int:
        """
        Automatically reconciles un-reconciled bank transactions against Orders (inflows) and Expenses (outflows).
        """
        unreconciled_txs = BankTransaction.objects.filter(
            bank_account=bank_account,
            user=user,
            is_reconciled=False
        )

        reconciled_count = 0
        with transaction.atomic():
            for tx in unreconciled_txs:
                # 1. Inflow transaction -> Match against Pending/Unpaid Orders
                if tx.amount > 0:
                    order = Order.objects.filter(
                        total=tx.amount,
                        complete=False
                    ).first()

                    if not order and tx.description:
                        # Try matching by transaction_id in order
                        order = Order.objects.filter(
                            transaction_id__icontains=tx.external_transaction_id
                        ).first()

                    if order:
                        ReconciliationRecord.objects.create(
                            user=user,
                            bank_transaction=tx,
                            order=order,
                            match_type='AUTOMATIC',
                            matched_amount=tx.amount,
                            discrepancy_amount=Decimal('0.00'),
                            status='RECONCILED'
                        )
                        tx.is_reconciled = True
                        tx.reconciled_at = django_timezone.now()
                        tx.save()

                        # Complete the matched order
                        order.complete = True
                        order.status = 'Paid'
                        order.transaction_id = tx.external_transaction_id or f"BANK_TX_{tx.id}"
                        order.save()

                        reconciled_count += 1
                        continue

                # 2. Outflow transaction -> Match against Expenses
                elif tx.amount < 0:
                    abs_amount = abs(tx.amount)
                    expense = Expense.objects.filter(
                        amount=abs_amount
                    ).first()

                    if expense:
                        ReconciliationRecord.objects.create(
                            user=user,
                            bank_transaction=tx,
                            expense=expense,
                            match_type='AUTOMATIC',
                            matched_amount=abs_amount,
                            discrepancy_amount=Decimal('0.00'),
                            status='RECONCILED'
                        )
                        tx.is_reconciled = True
                        tx.reconciled_at = django_timezone.now()
                        tx.save()
                        reconciled_count += 1

        return reconciled_count

    @staticmethod
    def manual_reconcile(
        user: User,
        bank_transaction_id: str,
        order_id: Optional[int] = None,
        expense_id: Optional[int] = None,
        notes: Optional[str] = None
    ) -> ReconciliationRecord:
        """
        Manually reconciles a bank transaction with an Order or Expense.
        """
        with transaction.atomic():
            tx = BankTransaction.objects.select_for_update().get(id=bank_transaction_id, user=user)
            order = Order.objects.get(id=order_id) if order_id else None
            expense = Expense.objects.get(id=expense_id) if expense_id else None

            target_amount = order.total if order else expense.amount if expense else abs(tx.amount)
            discrepancy = abs(abs(tx.amount) - target_amount)
            status = 'RECONCILED' if discrepancy == 0 else 'DISCREPANCY'

            rec_record = ReconciliationRecord.objects.create(
                user=user,
                bank_transaction=tx,
                order=order,
                expense=expense,
                match_type='MANUAL',
                matched_amount=target_amount,
                discrepancy_amount=discrepancy,
                status=status,
                notes=notes,
                reconciled_by=user
            )

            tx.is_reconciled = True
            tx.reconciled_at = django_timezone.now()
            tx.save()

            if order:
                order.complete = True
                order.status = 'Paid'
                order.transaction_id = tx.external_transaction_id or f"MANUAL_RECON_{tx.id}"
                order.save()

            BankingAuditLog.objects.create(
                user=user,
                action='RECONCILED',
                status='SUCCESS',
                details={
                    'transaction_id': str(tx.id),
                    'order_id': order_id,
                    'expense_id': expense_id,
                    'status': status
                }
            )

        return rec_record


class BankChargeService:
    @staticmethod
    def detect_and_record_charges(user: User, bank_account: BankAccount) -> int:
        """
        Scans bank transactions tagged as charges and creates BankCharge summary records.
        """
        charge_txs = BankTransaction.objects.filter(
            bank_account=bank_account,
            user=user,
            is_charge=True,
            bank_charge_record__isnull=True
        )

        recorded = 0
        with transaction.atomic():
            for tx in charge_txs:
                desc_lower = tx.description.lower()
                ctype = 'FEE'
                if 'commission' in desc_lower:
                    ctype = 'COMMISSION'
                elif 'interest' in desc_lower:
                    ctype = 'INTEREST'
                elif 'vat' in desc_lower or 'tax' in desc_lower:
                    ctype = 'VAT'

                BankCharge.objects.create(
                    user=user,
                    bank_account=bank_account,
                    bank_transaction=tx,
                    charge_type=ctype,
                    amount=abs(tx.amount),
                    description=tx.description,
                    charge_date=tx.transaction_date
                )
                recorded += 1
        return recorded


class AccountMonitoringService:
    @staticmethod
    def get_account_status_summary(user: User) -> Dict[str, Any]:
        """
        Monitors connected bank accounts, balances, charges, reconciliation rates, and connection health.
        """
        accounts = BankAccount.objects.filter(user=user)
        connections = BankAccountConnection.objects.filter(user=user)
        transactions = BankTransaction.objects.filter(user=user)
        charges = BankCharge.objects.filter(user=user)

        total_ledger = sum(acc.ledger_balance for acc in accounts)
        total_available = sum(acc.available_balance for acc in accounts)
        total_charges = sum(ch.amount for ch in charges)

        unreconciled_count = transactions.filter(is_reconciled=False).count()
        total_tx_count = transactions.count()

        reconciliation_rate = (
            round(((total_tx_count - unreconciled_count) / total_tx_count) * 100, 2)
            if total_tx_count > 0 else 100.0
        )

        connection_alerts = []
        for conn in connections:
            if conn.status == 'ERROR':
                connection_alerts.append(f"Provider {conn.provider_name} is in error state: {conn.error_details}")
            elif conn.status == 'PENDING':
                connection_alerts.append(f"Connection {conn.provider_name} requires explicit user authorization confirmation.")
            elif conn.last_synced_at and conn.last_synced_at < django_timezone.now() - timedelta(days=3):
                connection_alerts.append(f"Connection {conn.provider_name} has not synced in over 3 days.")

        return {
            'total_accounts': accounts.count(),
            'total_connections': connections.count(),
            'active_connections': connections.filter(status='CONNECTED').count(),
            'total_ledger_balance': float(total_ledger),
            'total_available_balance': float(total_available),
            'total_bank_charges': float(total_charges),
            'total_transactions': total_tx_count,
            'unreconciled_transactions': unreconciled_count,
            'reconciliation_rate': reconciliation_rate,
            'alerts': connection_alerts,
            'accounts': [
                {
                    'id': str(acc.id),
                    'bank_name': acc.bank_name,
                    'account_name': acc.account_name,
                    'mask': acc.account_number_mask,
                    'type': acc.account_type,
                    'balance': float(acc.ledger_balance),
                    'status': acc.status,
                    'transfers_enabled': acc.is_transfers_enabled
                }
                for acc in accounts
            ]
        }
