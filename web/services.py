import hmac
import hashlib
import json
import logging
import requests
from django.conf import settings
from django.db import transaction
from django.db.models import F
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from .models import Cart, CartItem, shoe, watch, Product, Order, Wishlist

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
        """Decrement stock and trigger alerts if stock is low."""
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

        # Trigger background notifications
        from .tasks import send_order_notification, send_order_receipt_email
        send_order_notification.delay(order.id, total_ngn, confirmed_acc)
        send_order_receipt_email.delay(order.id)

        # Admin real-time WebSocket notification
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
            "amount": int(amount * 100),  # In kobo
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
