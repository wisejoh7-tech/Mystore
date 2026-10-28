import json
import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse, HttpResponseBadRequest, Http404
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_http_methods

from .models import BankAccount, BankAccountConnection, BankTransaction, BankingAuditLog
from .services import (
    BankConnectionService,
    TransactionSyncService,
    StatementImportService,
    ReconciliationService,
    AccountMonitoringService
)
from .adapters import BankProviderRegistry, TransferNotAuthorizedError

logger = logging.getLogger(__name__)


@login_required
def bank_dashboard(request):
    """
    Banking integration dashboard view for tenant user.
    """
    summary = AccountMonitoringService.get_account_status_summary(request.user)
    transactions = BankTransaction.objects.filter(user=request.user).select_related('bank_account').order_by('-transaction_date')[:50]
    connections = BankAccountConnection.objects.filter(user=request.user)

    context = {
        'summary': summary,
        'transactions': transactions,
        'connections': connections,
    }
    return render(request, 'banking/dashboard.html', context)


@login_required
@require_POST
def bank_connect_initiate(request):
    """
    Initiates bank account connection flow.
    """
    try:
        data = json.loads(request.body) if request.body else request.POST
        provider_name = data.get('provider_name', 'mock')
        redirect_url = data.get('redirect_url')

        res = BankConnectionService.initiate_connection(request.user, provider_name, redirect_url)
        return JsonResponse({'status': 'success', 'data': res})
    except Exception as e:
        logger.error(f"Error initiating bank connection: {e}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


@login_required
@require_POST
def bank_connect_confirm(request):
    """
    Confirms provider token exchange and marks connection CONNECTED.
    """
    try:
        data = json.loads(request.body) if request.body else request.POST
        connection_id = data.get('connection_id')
        public_token = data.get('public_token')

        if not connection_id or not public_token:
            return JsonResponse({'status': 'error', 'message': 'Missing connection_id or public_token'}, status=400)

        conn = BankConnectionService.confirm_connection(request.user, connection_id, public_token)
        return JsonResponse({
            'status': 'success',
            'message': f"Bank connection confirmed with provider {conn.provider_name}",
            'connection_id': str(conn.id),
            'connection_status': conn.status
        })
    except Exception as e:
        logger.error(f"Error confirming bank connection: {e}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


@login_required
@require_POST
def bank_disconnect(request, connection_id):
    """
    Revokes bank connection.
    """
    try:
        BankConnectionService.disconnect_connection(request.user, str(connection_id))
        return JsonResponse({'status': 'success', 'message': 'Bank connection disconnected.'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


@login_required
@require_POST
def bank_sync_transactions(request, account_id):
    """
    Triggers manual sync of transactions for an account.
    """
    account = get_object_or_404(BankAccount, id=account_id, user=request.user)
    try:
        result = TransactionSyncService.sync_account_transactions(request.user, account)
        return JsonResponse({'status': 'success', 'data': result})
    except Exception as e:
        logger.error(f"Error syncing transactions: {e}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


@login_required
@require_POST
def bank_import_statement(request, account_id):
    """
    Imports bank statement CSV/JSON file.
    """
    account = get_object_or_404(BankAccount, id=account_id, user=request.user)
    try:
        file_obj = request.FILES.get('statement_file')
        file_format = request.POST.get('file_format', 'CSV')

        if not file_obj:
            return JsonResponse({'status': 'error', 'message': 'No file uploaded'}, status=400)

        content = file_obj.read().decode('utf-8', errors='ignore')
        stmt = StatementImportService.import_statement(
            user=request.user,
            bank_account=account,
            file_content=content,
            file_name=file_obj.name,
            file_format=file_format
        )

        return JsonResponse({
            'status': 'success',
            'statement_id': str(stmt.id),
            'imported_records': stmt.imported_records,
            'processing_status': stmt.status
        })
    except Exception as e:
        logger.error(f"Error importing statement: {e}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


@login_required
@require_POST
def bank_manual_reconcile(request):
    """
    Manually reconciles a transaction against an order or expense.
    """
    try:
        data = json.loads(request.body) if request.body else request.POST
        tx_id = data.get('transaction_id')
        order_id = data.get('order_id')
        expense_id = data.get('expense_id')
        notes = data.get('notes')

        rec = ReconciliationService.manual_reconcile(
            user=request.user,
            bank_transaction_id=tx_id,
            order_id=int(order_id) if order_id else None,
            expense_id=int(expense_id) if expense_id else None,
            notes=notes
        )

        return JsonResponse({
            'status': 'success',
            'reconciliation_id': str(rec.id),
            'reconciliation_status': rec.status
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


@csrf_exempt
@require_POST
def bank_webhook_handler(request, provider_name):
    """
    Webhook endpoint for bank provider webhooks with signature verification.
    """
    payload_bytes = request.body
    signature_header = (
        request.headers.get('X-Provider-Signature') or
        request.headers.get('X-Mono-Signature') or
        request.headers.get('X-Plaid-Verification') or
        request.META.get('HTTP_X_PROVIDER_SIGNATURE', '')
    )

    try:
        adapter = BankProviderRegistry.get_adapter(provider_name)
    except ValueError:
        return HttpResponseBadRequest("Unsupported provider webhook")

    if not adapter.verify_webhook_signature(payload_bytes, signature_header):
        logger.warning(f"Invalid webhook signature received for banking provider: {provider_name}")
        BankingAuditLog.objects.create(
            action='WEBHOOK_RECEIVED',
            status='BLOCKED',
            details={'provider': provider_name, 'reason': 'Invalid webhook signature'},
            ip_address=request.META.get('REMOTE_ADDR')
        )
        return HttpResponseBadRequest("Invalid signature")

    try:
        event_data = json.loads(payload_bytes.decode('utf-8'))
    except Exception:
        event_data = {}

    BankingAuditLog.objects.create(
        action='WEBHOOK_RECEIVED',
        status='SUCCESS',
        details={'provider': provider_name, 'event': event_data.get('event')},
        ip_address=request.META.get('REMOTE_ADDR')
    )

    return JsonResponse({'status': 'received'})
