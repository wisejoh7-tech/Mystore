from django.contrib import admin
from .models import User, shoe, Category, Order, watch, Expense, ContactMessage, Product

admin.site.register(User)
admin.site.register(shoe)
admin.site.register(Category)
admin.site.register(Order)
admin.site.register(watch)
admin.site.register(Expense)
admin.site.register(Product)


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'subject', 'created_at')
    search_fields = ('name', 'email', 'subject')
    list_filter = ('created_at',)
    readonly_fields = ('created_at',)


from .banking.models import (
    BankAccountConnection,
    BankAccount,
    BankTransaction,
    BankStatement,
    BankCharge,
    ReconciliationRecord,
    BankingAuditLog
)


@admin.register(BankAccountConnection)
class BankAccountConnectionAdmin(admin.ModelAdmin):
    list_display = ('user', 'provider_name', 'status', 'provider_confirmed_at', 'last_synced_at', 'created_at')
    list_filter = ('status', 'provider_name', 'created_at')
    search_fields = ('user__username', 'provider_name', 'external_connection_id')


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ('bank_name', 'account_name', 'account_number_mask', 'account_type', 'user', 'ledger_balance', 'status', 'is_transfers_enabled')
    list_filter = ('account_type', 'status', 'is_transfers_enabled')
    search_fields = ('bank_name', 'account_name', 'account_number_mask', 'user__username')


@admin.register(BankTransaction)
class BankTransactionAdmin(admin.ModelAdmin):
    list_display = ('bank_account', 'transaction_date', 'amount', 'currency', 'description', 'is_charge', 'is_reconciled')
    list_filter = ('is_charge', 'is_reconciled', 'transaction_date', 'currency')
    search_fields = ('description', 'external_transaction_id', 'bank_account__account_name')


@admin.register(BankStatement)
class BankStatementAdmin(admin.ModelAdmin):
    list_display = ('file_name', 'bank_account', 'file_format', 'imported_records', 'status', 'imported_at')
    list_filter = ('file_format', 'status', 'imported_at')
    search_fields = ('file_name', 'bank_account__bank_name')


@admin.register(BankCharge)
class BankChargeAdmin(admin.ModelAdmin):
    list_display = ('bank_account', 'charge_type', 'amount', 'charge_date', 'user')
    list_filter = ('charge_type', 'charge_date')
    search_fields = ('description', 'bank_account__bank_name')


@admin.register(ReconciliationRecord)
class ReconciliationRecordAdmin(admin.ModelAdmin):
    list_display = ('bank_transaction', 'order', 'expense', 'match_type', 'matched_amount', 'status', 'reconciled_at')
    list_filter = ('status', 'match_type', 'reconciled_at')
    search_fields = ('notes', 'user__username')


@admin.register(BankingAuditLog)
class BankingAuditLogAdmin(admin.ModelAdmin):
    list_display = ('action', 'status', 'user', 'ip_address', 'timestamp')
    list_filter = ('action', 'status', 'timestamp')
    search_fields = ('action', 'user__username', 'ip_address')
