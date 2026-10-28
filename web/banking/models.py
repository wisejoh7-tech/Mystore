import uuid
from django.db import models
from django.conf import settings
from web.models import Order, Expense


class BankAccountConnection(models.Model):
    STATUS_CHOICES = (
        ('DISCONNECTED', 'Disconnected'),
        ('PENDING', 'Pending Authorization'),
        ('CONNECTED', 'Connected'),
        ('ERROR', 'Error'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='bank_connections',
        help_text='Tenant / Business user owning this bank connection'
    )
    provider_name = models.CharField(max_length=50, help_text='Bank integration provider, e.g., mock, plaid, mono')
    external_connection_id = models.CharField(max_length=255, db_index=True, blank=True, null=True)
    encrypted_access_token = models.TextField(blank=True, null=True, help_text='Encrypted access token for API requests')
    encrypted_refresh_token = models.TextField(blank=True, null=True, help_text='Encrypted refresh token')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DISCONNECTED', db_index=True)
    provider_confirmed_at = models.DateTimeField(null=True, blank=True, help_text='Timestamp when provider confirmed active authorization')
    last_synced_at = models.DateTimeField(null=True, blank=True)
    error_details = models.TextField(blank=True, null=True)
    raw_metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['provider_name', 'external_connection_id']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.provider_name} ({self.status})"


class BankAccount(models.Model):
    ACCOUNT_TYPES = (
        ('CHECKING', 'Checking Account'),
        ('SAVINGS', 'Savings Account'),
        ('CREDIT', 'Credit Account'),
        ('BUSINESS', 'Business Account'),
        ('OTHER', 'Other Account'),
    )

    STATUS_CHOICES = (
        ('ACTIVE', 'Active'),
        ('INACTIVE', 'Inactive'),
        ('SUSPENDED', 'Suspended'),
        ('CLOSED', 'Closed'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='bank_accounts'
    )
    connection = models.ForeignKey(
        BankAccountConnection,
        on_delete=models.CASCADE,
        related_name='accounts',
        null=True,
        blank=True
    )
    external_account_id = models.CharField(max_length=255, db_index=True, blank=True, null=True)
    bank_name = models.CharField(max_length=150)
    account_name = models.CharField(max_length=150)
    account_number_mask = models.CharField(max_length=20, help_text='Masked account number, e.g. ****1234')
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPES, default='CHECKING')
    currency = models.CharField(max_length=10, default='NGN')
    ledger_balance = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    available_balance = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE', db_index=True)
    is_transfers_enabled = models.BooleanField(
        default=False,
        help_text='Guardrail: Transfers and payment initiation are disabled by default until explicitly authorized & tested.'
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'status']),
        ]

    def __str__(self):
        return f"{self.bank_name} - {self.account_name} ({self.account_number_mask})"


class BankTransaction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='bank_transactions'
    )
    bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.CASCADE,
        related_name='transactions'
    )
    external_transaction_id = models.CharField(
        max_length=255,
        db_index=True,
        blank=True,
        null=True,
        help_text='Unique external provider transaction reference for idempotency'
    )
    transaction_date = models.DateTimeField(db_index=True)
    posted_date = models.DateTimeField(null=True, blank=True)
    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        help_text='Transaction amount. Positive for credits/inflows, negative for debits/outflows'
    )
    currency = models.CharField(max_length=10, default='NGN')
    description = models.TextField()
    category = models.CharField(max_length=100, blank=True, null=True)
    is_charge = models.BooleanField(default=False, help_text='Identified as bank charge/fee')
    is_reconciled = models.BooleanField(default=False, db_index=True)
    reconciled_at = models.DateTimeField(null=True, blank=True)
    raw_metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['bank_account', 'external_transaction_id'],
                condition=models.Q(external_transaction_id__isnull=False),
                name='unique_account_external_tx_id'
            )
        ]
        indexes = [
            models.Index(fields=['user', 'transaction_date']),
            models.Index(fields=['bank_account', 'is_reconciled']),
        ]

    def __str__(self):
        return f"[{self.transaction_date.strftime('%Y-%m-%d')}] {self.amount} {self.currency} - {self.description[:30]}"


class BankStatement(models.Model):
    FORMAT_CHOICES = (
        ('CSV', 'CSV File'),
        ('OFX', 'OFX / QFX File'),
        ('JSON', 'JSON Data'),
    )

    STATUS_CHOICES = (
        ('PENDING', 'Pending Processing'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='bank_statements'
    )
    bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.CASCADE,
        related_name='statements'
    )
    file_name = models.CharField(max_length=255)
    file_format = models.CharField(max_length=10, choices=FORMAT_CHOICES, default='CSV')
    imported_at = models.DateTimeField(auto_now_add=True, db_index=True)
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    total_records = models.IntegerField(default=0)
    imported_records = models.IntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING', db_index=True)
    error_message = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Statement {self.file_name} for {self.bank_account.bank_name}"


class BankCharge(models.Model):
    CHARGE_TYPES = (
        ('FEE', 'Bank Fee / Maintenance'),
        ('COMMISSION', 'Transfer / Service Commission'),
        ('INTEREST', 'Interest Charge'),
        ('VAT', 'Tax / VAT'),
        ('OTHER', 'Other Bank Charge'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='bank_charges'
    )
    bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.CASCADE,
        related_name='charges'
    )
    bank_transaction = models.OneToOneField(
        BankTransaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bank_charge_record'
    )
    charge_type = models.CharField(max_length=20, choices=CHARGE_TYPES, default='FEE')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.CharField(max_length=255)
    charge_date = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.charge_type}: {self.amount} ({self.bank_account.bank_name})"


class ReconciliationRecord(models.Model):
    MATCH_TYPES = (
        ('AUTOMATIC', 'Automatic Match'),
        ('MANUAL', 'Manual Match'),
    )

    STATUS_CHOICES = (
        ('RECONCILED', 'Reconciled'),
        ('DISCREPANCY', 'Discrepancy'),
        ('UNRECONCILED', 'Unreconciled'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reconciliations'
    )
    bank_transaction = models.ForeignKey(
        BankTransaction,
        on_delete=models.CASCADE,
        related_name='reconciliation_records'
    )
    order = models.ForeignKey(
        Order,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bank_reconciliations'
    )
    expense = models.ForeignKey(
        Expense,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bank_reconciliations'
    )
    match_type = models.CharField(max_length=20, choices=MATCH_TYPES, default='AUTOMATIC')
    matched_amount = models.DecimalField(max_digits=15, decimal_places=2)
    discrepancy_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='RECONCILED', db_index=True)
    notes = models.TextField(blank=True, null=True)
    reconciled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='performed_reconciliations'
    )
    reconciled_at = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self):
        target = f"Order #{self.order.id}" if self.order else f"Expense #{self.expense.id}" if self.expense else "General"
        return f"Reconciliation {self.status} for {target} - TX {self.bank_transaction.id}"


class BankingAuditLog(models.Model):
    ACTION_CHOICES = (
        ('CONNECTION_REQUEST', 'Connection Requested'),
        ('CONNECTION_CONFIRMED', 'Connection Confirmed by Provider'),
        ('CONNECTION_REVOKED', 'Connection Revoked'),
        ('SYNC_STARTED', 'Sync Started'),
        ('SYNC_COMPLETED', 'Sync Completed'),
        ('STATEMENT_IMPORTED', 'Statement Imported'),
        ('RECONCILED', 'Transaction Reconciled'),
        ('WEBHOOK_RECEIVED', 'Webhook Event Received'),
        ('TRANSFER_BLOCKED', 'Transfer Attempt Blocked by Guardrail'),
        ('TRANSFER_EXECUTED', 'Transfer Executed'),
    )

    STATUS_CHOICES = (
        ('SUCCESS', 'Success'),
        ('FAILURE', 'Failure'),
        ('BLOCKED', 'Blocked Guardrail'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='banking_audit_logs'
    )
    action = models.CharField(max_length=30, choices=ACTION_CHOICES, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='SUCCESS', db_index=True)
    details = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"[{self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}] {self.action} - {self.status}"
