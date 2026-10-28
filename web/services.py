import csv
import io
import re
import hmac
import hashlib
import json
import logging
import requests
from decimal import Decimal
from datetime import datetime, timedelta, date
from django.conf import settings
from django.db import transaction
from django.db.models import F, Q, Sum
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from .models import (
    Cart, CartItem, shoe, watch, Product, Order, Wishlist, Expense,
    BankAccount, BankTransaction, BankReconciliation, BankingAuditLog
)

logger = logging.getLogger(__name__)


class CartService:
    @staticmethod
    def get_or_create_cart(user=None, session_key=None):
        if user and user.is_authenticated:
            cart, _ = Cart.objects.get_or_create(user=user)
        elif session_key:
            cart, _ = Cart.objects.get_or_create(session_key=session_key)
        else:
            cart = None
        return cart

    @staticmethod
    def add_to_cart(cart, prod_type, prod_id, quantity=1):
        if not cart:
            raise ValueError("Cart object is required")

        if prod_type == 'shoe':
            item = shoe.objects.get(id=prod_id)
            cart_item, created = CartItem.objects.get_or_create(cart=cart, shoe_item=item)
        elif prod_type == 'watch':
            item = watch.objects.get(id=prod_id)
            cart_item, created = CartItem.objects.get_or_create(cart=cart, watch_item=item)
        else:
            item = Product.objects.get(id=prod_id)
            cart_item, created = CartItem.objects.get_or_create(cart=cart, product_item=item)

        if not created:
            cart_item.quantity += quantity
        else:
            cart_item.quantity = quantity
        cart_item.save()
        return cart_item

    @staticmethod
    def remove_from_cart(cart, item_id):
        if not cart:
            return False
        CartItem.objects.filter(cart=cart, id=item_id).delete()
        return True

    @staticmethod
    def sync_cart(user, local_cart):
        db_cart, _ = Cart.objects.get_or_create(user=user)
        for item in local_cart:
            shoe_id = item.get('shoeId')
            watch_id = item.get('watchId')
            quantity = int(item.get('quantity', 1))

            if shoe_id:
                try:
                    prod = shoe.objects.get(id=shoe_id)
                    cart_item, created = CartItem.objects.get_or_create(cart=db_cart, shoe_item=prod)
                    cart_item.quantity = min(10, cart_item.quantity + quantity if not created else quantity)
                    cart_item.save()
                except shoe.DoesNotExist:
                    continue
            elif watch_id:
                try:
                    prod = watch.objects.get(id=watch_id)
                    cart_item, created = CartItem.objects.get_or_create(cart=db_cart, watch_item=prod)
                    cart_item.quantity = min(10, cart_item.quantity + quantity if not created else quantity)
                    cart_item.save()
                except watch.DoesNotExist:
                    continue
        return db_cart

    @staticmethod
    def get_cart_data(cart):
        if not cart:
            return []
        items = []
        cart_items = cart.items.select_related('shoe_item', 'watch_item', 'product_item').all()
        for item in cart_items:
            prod = item.shoe_item or item.watch_item or item.product_item
            if prod:
                items.append({
                    'id': item.id,
                    'name': prod.name,
                    'quantity': item.quantity,
                    'price': float(prod.discount_price or prod.price),
                    'image': prod.image.url if prod.image else ''
                })
        return items


class InventoryService:
    @staticmethod
    def decrement_stock(items_json):
        from .tasks import send_low_stock_alert
        try:
            items = json.loads(items_json) if isinstance(items_json, str) else items_json
            with transaction.atomic():
                for item in items:
                    qty = int(item.get('quantity', 1))
                    product = None
                    ptype = ""

                    if 'shoeId' in item:
                        product = shoe.objects.select_for_update().filter(id=item['shoeId']).first()
                        ptype = "shoe"
                    elif 'watchId' in item:
                        product = watch.objects.select_for_update().filter(id=item['watchId']).first()
                        ptype = "watch"
                    elif 'productId' in item:
                        product = Product.objects.select_for_update().filter(id=item['productId']).first()
                        ptype = "product"

                    if product:
                        product.stock = F('stock') - qty
                        product.save()
                        product.refresh_from_db()

                        if product.stock <= 5:
                            send_low_stock_alert.delay(ptype, product.id, product.stock)
        except Exception as e:
            logger.error(f"Error reducing stock: {e}")


class OrderService:
    @staticmethod
    def create_order(user, cart_json, delivery_address, phone, payment_method, confirmed_acc=None):
        if not cart_json or cart_json == 'null':
            raise ValueError("Cart data is missing.")

        cart_data = json.loads(cart_json) if isinstance(cart_json, str) else cart_json
        if not cart_data:
            raise ValueError("Cart is empty.")

        total_ngn = 0
        for item in cart_data:
            price = float(item.get('watchPrice') or item.get('shoePrice') or item.get('price') or 0)
            qty = int(item.get('quantity') or 1)
            total_ngn += price * qty

        with transaction.atomic():
            order = Order.objects.create(
                user=user if (user and user.is_authenticated) else None,
                items_json=json.dumps(cart_data) if isinstance(cart_data, list) else cart_json,
                total=total_ngn,
                delivery_address=delivery_address,
                phone=phone,
                status='Pending',
                payment_method=payment_method,
                confirmed_account_number=confirmed_acc if payment_method == 'Bank Transfer' else None
            )

            if user and user.is_authenticated:
                Cart.objects.filter(user=user).delete()

        from .tasks import send_order_notification, send_order_receipt_email
        send_order_notification.delay(order.id, total_ngn, confirmed_acc)
        send_order_receipt_email.delay(order.id)

        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                "admin_notifications",
                {
                    "type": "send_notification",
                    "content": {
                        "title": "New Order Placed",
                        "message": f"Order #{order.id} for ₦{total_ngn} (Method: {payment_method})",
                        "url": "/admin-dashboard/"
                    }
                }
            )

        return order

    @staticmethod
    def complete_order(order, reference=None):
        with transaction.atomic():
            order = Order.objects.select_for_update().get(id=order.id)
            if not order.complete:
                order.complete = True
                order.status = "Paid"
                if reference:
                    order.transaction_id = reference
                order.save()

                InventoryService.decrement_stock(order.items_json)

                from .tasks import send_order_notification, send_order_receipt_email
                send_order_notification.delay(order.id, order.total, f"Paystack Reference: {reference}")
                send_order_receipt_email.delay(order.id)

                channel_layer = get_channel_layer()
                if channel_layer:
                    async_to_sync(channel_layer.group_send)(
                        "admin_notifications",
                        {
                            "type": "send_notification",
                            "content": {
                                "title": "New Payment Received",
                                "message": f"Order #{order.id} has been paid (₦{order.total})",
                                "url": "/admin-dashboard/"
                            }
                        }
                    )
        return order


class PaymentService:
    @staticmethod
    def initialize_paystack_transaction(user_email, amount, callback_url, order_id):
        url = "https://api.paystack.co/transaction/initialize"
        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json",
        }
        data = {
            "email": user_email,
            "amount": int(amount * 100),
            "callback_url": callback_url,
            "metadata": {
                "order_id": order_id
            }
        }
        try:
            response = requests.post(url, headers=headers, json=data, timeout=10)
            return response.json()
        except requests.RequestException as exc:
            logger.error(f"Paystack initialization error: {exc}")
            return {"status": False, "message": "Connection error to Paystack"}

    @staticmethod
    def verify_paystack_transaction(reference):
        url = f"https://api.paystack.co/transaction/verify/{reference}"
        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        }
        try:
            response = requests.get(url, headers=headers, timeout=10)
            return response.json()
        except requests.RequestException as exc:
            logger.error(f"Paystack verification error: {exc}")
            return {"status": False, "message": "Connection error to Paystack"}

    @staticmethod
    def verify_webhook_signature(payload_bytes, signature_header):
        if not signature_header or not settings.PAYSTACK_SECRET_KEY:
            return False
        expected_signature = hmac.new(
            settings.PAYSTACK_SECRET_KEY.encode('utf-8'),
            payload_bytes,
            hashlib.sha512
        ).hexdigest()
        return hmac.compare_digest(expected_signature, signature_header)

    @staticmethod
    def process_webhook_event(event_data):
        event_type = event_data.get('event')
        data = event_data.get('data', {})

        if event_type == 'charge.success':
            reference = data.get('reference')
            metadata = data.get('metadata', {})
            order_id = metadata.get('order_id')

            if order_id:
                try:
                    order = Order.objects.get(id=order_id)
                    OrderService.complete_order(order, reference=reference)
                    return True, "Order completed"
                except Order.DoesNotExist:
                    logger.error(f"Webhook received for non-existent order ID: {order_id}")
                    return False, "Order not found"
        return True, "Event processed or ignored"


# ==========================================
# BANKING AND FINANCIAL SERVICES
# ==========================================

class BankAccountService:
    @staticmethod
    def mask_account_number(account_number):
        clean_num = re.sub(r'\D', '', str(account_number or ''))
        if len(clean_num) <= 4:
            return "****" + clean_num
        return "*" * (len(clean_num) - 4) + clean_num[-4:]

    @staticmethod
    def create_account(user, bank_name, account_name, raw_account_number, currency="NGN", opening_balance=0.0, organization="MyStore HQ", branch="Main Branch"):
        masked = BankAccountService.mask_account_number(raw_account_number)
        opening_bal_dec = Decimal(str(opening_balance))
        account = BankAccount.objects.create(
            bank_name=bank_name,
            account_name=account_name,
            masked_account_number=masked,
            currency=currency,
            opening_balance=opening_bal_dec,
            current_balance=opening_bal_dec,
            organization_name=organization,
            branch_name=branch
        )
        BankingAuditService.log(user, "CREATE_BANK_ACCOUNT", f"Created account {account.bank_name} ({account.masked_account_number})")
        return account

    @staticmethod
    def recalculate_balance(account):
        deposits = BankTransaction.objects.filter(bank_account=account, status='Completed', transaction_type='Deposit').aggregate(total=Sum('amount'))['total'] or Decimal('0.0')
        withdrawals = BankTransaction.objects.filter(bank_account=account, status='Completed', transaction_type__in=['Withdrawal', 'Transfer', 'Bank Charge']).aggregate(total=Sum('amount'))['total'] or Decimal('0.0')
        account.current_balance = Decimal(str(account.opening_balance)) + deposits - withdrawals
        account.save()
        return account.current_balance


class BankStatementImportService:
    @staticmethod
    def sanitize_csv_cell(value):
        text = str(value or '').strip()
        if text.startswith(('=', '+', '-', '@')):
            return "'" + text
        return text

    @staticmethod
    def parse_date(date_val):
        if isinstance(date_val, (date, datetime)):
            return date_val.date() if isinstance(date_val, datetime) else date_val
        date_str = str(date_val).strip()
        for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%d-%m-%Y', '%Y/%m/%d'):
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        raise ValueError(f"Invalid date format: {date_str}")

    @staticmethod
    def preview_csv_import(bank_account, csv_file_bytes):
        file_text = csv_file_bytes.decode('utf-8', errors='ignore')
        reader = csv.DictReader(io.StringIO(file_text))

        parsed_rows = []
        duplicate_count = 0
        error_count = 0

        for row_idx, row in enumerate(reader, start=1):
            try:
                date_val = BankStatementImportService.parse_date(row.get('date') or row.get('Date'))
                amount_val = Decimal(re.sub(r'[^\d.-]', '', row.get('amount') or row.get('Amount') or '0'))
                type_val = BankStatementImportService.sanitize_csv_cell(row.get('type') or row.get('Type') or 'Deposit')
                ref_val = BankStatementImportService.sanitize_csv_cell(row.get('reference') or row.get('Reference') or row.get('ref') or '')
                desc_val = BankStatementImportService.sanitize_csv_cell(row.get('description') or row.get('Description') or '')

                dummy_tx = BankTransaction(
                    bank_account=bank_account,
                    transaction_date=date_val,
                    amount=amount_val,
                    reference_number=ref_val,
                    description=desc_val
                )
                tx_hash = dummy_tx.generate_hash()
                is_duplicate = BankTransaction.objects.filter(deduplication_hash=tx_hash).exists()

                if is_duplicate:
                    duplicate_count += 1

                parsed_rows.append({
                    'row_num': row_idx,
                    'date': date_val.strftime('%Y-%m-%d'),
                    'amount': float(amount_val),
                    'type': type_val,
                    'reference': ref_val,
                    'description': desc_val,
                    'hash': tx_hash,
                    'is_duplicate': is_duplicate
                })
            except Exception as e:
                error_count += 1
                parsed_rows.append({
                    'row_num': row_idx,
                    'error': str(e),
                    'is_invalid': True
                })

        return {
            'total_rows': len(parsed_rows),
            'duplicate_count': duplicate_count,
            'error_count': error_count,
            'rows': parsed_rows
        }

    @staticmethod
    def confirm_csv_import(user, bank_account, valid_rows):
        created_count = 0
        with transaction.atomic():
            for row in valid_rows:
                if row.get('is_duplicate') or row.get('is_invalid'):
                    continue

                tx, created = BankTransaction.objects.get_or_create(
                    deduplication_hash=row['hash'],
                    defaults={
                        'bank_account': bank_account,
                        'transaction_date': datetime.strptime(row['date'], '%Y-%m-%d').date(),
                        'amount': Decimal(str(row['amount'])),
                        'transaction_type': row.get('type', 'Deposit'),
                        'reference_number': row.get('reference', ''),
                        'description': row.get('description', ''),
                        'currency': bank_account.currency,
                        'source': 'CSV_IMPORT',
                        'status': 'Completed'
                    }
                )
                if created:
                    created_count += 1

            BankAccountService.recalculate_balance(bank_account)
            BankingAuditService.log(user, "IMPORT_STATEMENT", f"Imported {created_count} bank transactions into {bank_account.bank_name}")

        return created_count


class ReconciliationService:
    @staticmethod
    def suggest_matches(bank_transaction):
        if bank_transaction.status == 'Reconciled':
            return None

        tx_date = BankStatementImportService.parse_date(bank_transaction.transaction_date)
        start_date = tx_date - timedelta(days=3)
        end_date = tx_date + timedelta(days=3)

        if bank_transaction.transaction_type in ['Deposit']:
            orders = Order.objects.filter(
                complete=True,
                total=bank_transaction.amount,
                created_at__date__gte=start_date,
                created_at__date__lte=end_date
            ).exclude(bank_reconciliations__status='Confirmed')[:3]
            return {'type': 'order', 'matches': list(orders)}
        else:
            expenses = Expense.objects.filter(
                amount=bank_transaction.amount,
                date__date__gte=start_date,
                date__date__lte=end_date
            ).exclude(bank_reconciliations__status='Confirmed')[:3]
            return {'type': 'expense', 'matches': list(expenses)}

    @staticmethod
    def confirm_match(user, bank_transaction, order=None, expense=None, notes=""):
        with transaction.atomic():
            recon, created = BankReconciliation.objects.get_or_create(
                bank_transaction=bank_transaction,
                defaults={
                    'order': order,
                    'expense': expense,
                    'matched_by': user,
                    'status': 'Confirmed',
                    'notes': notes
                }
            )
            if not created:
                recon.order = order
                recon.expense = expense
                recon.matched_by = user
                recon.status = 'Confirmed'
                recon.notes = notes
                recon.save()

            bank_transaction.status = 'Reconciled'
            bank_transaction.save()

            BankingAuditService.log(user, "CONFIRM_RECONCILIATION", f"Reconciled transaction #{bank_transaction.id} with Order #{order.id if order else 'None'}/Expense #{expense.id if expense else 'None'}")
        return recon

    @staticmethod
    def undo_match(user, bank_transaction):
        with transaction.atomic():
            if hasattr(bank_transaction, 'reconciliation'):
                recon = bank_transaction.reconciliation
                recon.status = 'Unmatched'
                recon.order = None
                recon.expense = None
                recon.save()

            bank_transaction.status = 'Completed'
            bank_transaction.save()

            BankingAuditService.log(user, "UNDO_RECONCILIATION", f"Undid reconciliation for bank transaction #{bank_transaction.id}")


class BankingIntegrationService:
    @staticmethod
    def is_configured():
        return bool(settings.PAYSTACK_SECRET_KEY)

    @staticmethod
    def fetch_live_balance(account_number, bank_code):
        if not BankingIntegrationService.is_configured():
            return {"status": False, "message": "Live Banking API credentials not configured."}
        return {"status": False, "message": "Live balance sync disabled by security policy."}


class BankingAuditService:
    @staticmethod
    def log(user, action, details, ip_address=None):
        BankingAuditLog.objects.create(
            user=user if (user and user.is_authenticated) else None,
            action=action,
            details=details,
            ip_address=ip_address
        )
