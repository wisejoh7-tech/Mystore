import json
import hmac
import hashlib
from io import BytesIO
from PIL import Image
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from django.conf import settings
from .models import User, Category, shoe, watch, Cart, CartItem, Order, ContactMessage, Product
from .services import CartService, InventoryService, OrderService, PaymentService


def create_test_image():
    file_obj = BytesIO()
    img = Image.new('RGB', (100, 100), color='red')
    img.save(file_obj, 'jpeg')
    file_obj.seek(0)
    return SimpleUploadedFile("test.jpg", file_obj.read(), content_type="image/jpeg")


class ModelTests(TestCase):
    def test_category_creation(self):
        cat = Category.objects.create(name="Footwear", description="All shoes")
        self.assertEqual(str(cat), "Footwear")

    def test_shoe_creation(self):
        cat = Category.objects.create(name="Footwear")
        s = shoe.objects.create(name="Air Max", brand="Nike", category=cat, price=150.00)
        self.assertEqual(str(s), "Nike Air Max")

    def test_watch_creation(self):
        cat = Category.objects.create(name="Accessories")
        w = watch.objects.create(name="G-Shock", brand="Casio", category=cat, price=100.00)
        self.assertEqual(str(w), "Casio G-Shock")

    def test_user_creation(self):
        user = User.objects.create_user(username="testuser", email="test@example.com", password="password123")
        self.assertEqual(str(user), "testuser")
        self.assertTrue(user.check_password("password123"))

    def test_cart_total_price(self):
        cat = Category.objects.create(name="Footwear")
        s = shoe.objects.create(name="Sneakers", category=cat, price=50.00)
        cart = Cart.objects.create()
        CartItem.objects.create(cart=cart, shoe_item=s, quantity=2)
        self.assertEqual(cart.total_price, 100.00)

    def test_order_items_list(self):
        items_data = [
            {'shoeId': 1, 'shoeName': 'Running Shoes', 'shoePrice': 80.0, 'quantity': 1}
        ]
        order = Order.objects.create(
            items_json=json.dumps(items_data),
            total=80.0,
            status='Pending'
        )
        items = order.items_list
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['name'], 'Running Shoes')


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
    DEFAULT_FILE_STORAGE="django.core.files.storage.InMemoryStorage",
)
class ViewTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_home_view_status_code(self):
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)

    def test_cart_view_status_code(self):
        response = self.client.get(reverse('cart'))
        self.assertEqual(response.status_code, 200)

    def test_search_view(self):
        cat = Category.objects.create(name="Watches")
        dummy_img = create_test_image()
        watch.objects.create(name="Rolex Submariner", brand="Rolex", category=cat, price=5000.00, image=dummy_img)
        response = self.client.get(reverse('search'), {'q': 'Rolex'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Rolex Submariner")

    def test_contact_view_post(self):
        response = self.client.post(reverse('contact'), {
            'name': 'John Doe',
            'email': 'john@example.com',
            'subject': 'Inquiry',
            'message': 'Hello world'
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ContactMessage.objects.count(), 1)
        msg = ContactMessage.objects.first()
        self.assertEqual(msg.name, 'John Doe')


class ServiceLayerTests(TestCase):
    def setUp(self):
        self.cat = Category.objects.create(name="General")
        self.shoe_item = shoe.objects.create(name="Air Force 1", category=self.cat, price=100.00, stock=10)
        self.user = User.objects.create_user(username="serviceuser", email="service@example.com", password="password123")

    def test_cart_service_add_and_get_data(self):
        cart = CartService.get_or_create_cart(user=self.user)
        CartService.add_to_cart(cart, 'shoe', self.shoe_item.id, quantity=2)
        data = CartService.get_cart_data(cart)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['quantity'], 2)
        self.assertEqual(data[0]['name'], 'Air Force 1')

    def test_inventory_service_decrement(self):
        items = [{'shoeId': self.shoe_item.id, 'quantity': 3}]
        InventoryService.decrement_stock(json.dumps(items))
        self.shoe_item.refresh_from_db()
        self.assertEqual(self.shoe_item.stock, 7)

    def test_order_service_creation_and_completion(self):
        items = [{'shoeId': self.shoe_item.id, 'shoePrice': 100.00, 'quantity': 2}]
        order = OrderService.create_order(
            user=self.user,
            cart_json=json.dumps(items),
            delivery_address="123 Test St",
            phone="08000000000",
            payment_method="Bank Transfer"
        )
        self.assertEqual(order.total, 200.00)
        self.assertFalse(order.complete)

        OrderService.complete_order(order, reference="REF123456")
        order.refresh_from_db()
        self.assertTrue(order.complete)
        self.assertEqual(order.status, "Paid")
        self.assertEqual(order.transaction_id, "REF123456")

        self.shoe_item.refresh_from_db()
        self.assertEqual(self.shoe_item.stock, 8)


class PaystackWebhookTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="webhookuser", email="webhook@example.com", password="password123")
        self.cat = Category.objects.create(name="Shoes")
        self.shoe_item = shoe.objects.create(name="Runner", category=self.cat, price=50.00, stock=10)
        items = [{'shoeId': self.shoe_item.id, 'shoePrice': 50.00, 'quantity': 1}]
        self.order = OrderService.create_order(
            user=self.user,
            cart_json=json.dumps(items),
            delivery_address="456 Webhook Ave",
            phone="08011111111",
            payment_method="Card Payment"
        )

    def test_webhook_invalid_signature(self):
        payload = json.dumps({'event': 'charge.success'})
        response = self.client.post(
            reverse('paystack_webhook'),
            data=payload,
            content_type='application/json',
            HTTP_X_PAYSTACK_SIGNATURE='bad_signature'
        )
        self.assertEqual(response.status_code, 400)

    def test_webhook_valid_signature_and_idempotency(self):
        payload_data = {
            'event': 'charge.success',
            'data': {
                'reference': 'PAYSTACK_REF_999',
                'metadata': {
                    'order_id': self.order.id
                }
            }
        }
        payload_bytes = json.dumps(payload_data).encode('utf-8')
        signature = hmac.new(
            settings.PAYSTACK_SECRET_KEY.encode('utf-8'),
            payload_bytes,
            hashlib.sha512
        ).hexdigest()

        # First webhook delivery
        response = self.client.post(
            reverse('paystack_webhook'),
            data=payload_bytes,
            content_type='application/json',
            HTTP_X_PAYSTACK_SIGNATURE=signature
        )
        self.assertEqual(response.status_code, 200)

        self.order.refresh_from_db()
        self.assertTrue(self.order.complete)
        self.assertEqual(self.order.status, "Paid")
        self.shoe_item.refresh_from_db()
        self.assertEqual(self.shoe_item.stock, 9)

        # Duplicate webhook delivery (Idempotency check)
        response_dup = self.client.post(
            reverse('paystack_webhook'),
            data=payload_bytes,
            content_type='application/json',
            HTTP_X_PAYSTACK_SIGNATURE=signature
        )
        self.assertEqual(response_dup.status_code, 200)
        self.shoe_item.refresh_from_db()
        # Stock should NOT be decremented again
        self.assertEqual(self.shoe_item.stock, 9)


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
    DEFAULT_FILE_STORAGE="django.core.files.storage.InMemoryStorage",
)
class PaginationAndPerformanceTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.cat = Category.objects.create(name="BulkCategory")
        for i in range(25):
            dummy_img = create_test_image()
            shoe.objects.create(name=f"Shoe {i}", target_audience="Male", category=self.cat, price=100 + i, image=dummy_img)

    def test_men_view_pagination(self):
        response = self.client.get(reverse('men'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('page_obj', response.context)
        page_obj = response.context['page_obj']
        self.assertEqual(len(page_obj), 12)
        self.assertEqual(page_obj.paginator.num_pages, 3)

    def test_men_view_query_count(self):
        # Ensure query count is bounded and optimized with select_related
        with self.assertNumQueries(4):
            response = self.client.get(reverse('men'))
            self.assertEqual(response.status_code, 200)


class DatabaseConfigTests(TestCase):
    def test_database_url_fallback_and_config(self):
        import os
        import dj_database_url

        default_url = os.getenv("DATABASE_URL", "postgres://postgres:postgres@127.0.0.1:5432/my_store_db")
        db_config = dj_database_url.config(default=default_url, conn_max_age=600)
        self.assertIn('ENGINE', db_config)
        self.assertIn('NAME', db_config)

    def test_format_render_database_url(self):
        from drop.settings import format_render_database_url

        short_url = "postgres://user:pass@dpg-db2hhvui0phs73enh0o0-a/drop_db"
        formatted = format_render_database_url(short_url)
        self.assertEqual(formatted, "postgres://user:pass@dpg-db2hhvui0phs73enh0o0-a.oregon-postgres.render.com/drop_db")

        full_url = "postgres://user:pass@dpg-db2hhvui0phs73enh0o0-a.oregon-postgres.render.com/drop_db"
        self.assertEqual(format_render_database_url(full_url), full_url)

        local_url = "postgres://postgres:postgres@127.0.0.1:5432/my_store_db"
        self.assertEqual(format_render_database_url(local_url), local_url)

        self.assertEqual(format_render_database_url(""), "")


class AdminPasswordResetTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_reset_admin_password_management_command(self):
        from django.core.management import call_command
        from io import StringIO

        out = StringIO()
        call_command("reset_admin_password", username="admin_test", password="NewPassword123!", email="admin@test.com", stdout=out)
        user = User.objects.get(username="admin_test")
        self.assertTrue(user.check_password("NewPassword123!"))
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)

        call_command("reset_admin_password", username="admin_test", password="UpdatedPassword123!", stdout=out)
        user.refresh_from_db()
        self.assertTrue(user.check_password("UpdatedPassword123!"))

    def test_password_reset_views_status_code(self):
        response = self.client.get(reverse('password_reset'))
        self.assertEqual(response.status_code, 200)

        response = self.client.get(reverse('password_reset_done'))
        self.assertEqual(response.status_code, 200)

    def test_clear_users_management_command(self):
        from django.core.management import call_command
        from io import StringIO

        User.objects.create_user(username="regular1", email="reg1@test.com", password="Password123")
        User.objects.create_user(username="regular2", email="reg2@test.com", password="Password123")
        self.assertEqual(User.objects.filter(is_staff=False).count(), 2)

        out = StringIO()
        call_command("clear_users", stdout=out)
        self.assertEqual(User.objects.filter(is_staff=False).count(), 0)

    def test_login_page_forgot_password_links(self):
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('password_reset'))
        self.assertContains(response, "Forgotten Password?")
        self.assertContains(response, "Reset Password")


class EmailOrUsernameAuthTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.superuser = User.objects.create_superuser(
            username="superadmin",
            email="admin@mystore.com",
            password="AdminPassword123!"
        )

    def test_authenticate_by_username(self):
        from django.contrib.auth import authenticate
        user = authenticate(username="superadmin", password="AdminPassword123!")
        self.assertIsNotNone(user)
        self.assertEqual(user, self.superuser)

    def test_authenticate_by_email(self):
        from django.contrib.auth import authenticate
        user = authenticate(username="admin@mystore.com", password="AdminPassword123!")
        self.assertIsNotNone(user)
        self.assertEqual(user, self.superuser)

    def test_authenticate_case_insensitive_email(self):
        from django.contrib.auth import authenticate
        user = authenticate(username="ADMIN@MYSTORE.COM", password="AdminPassword123!")
        self.assertIsNotNone(user)
        self.assertEqual(user, self.superuser)

    def test_admin_login_with_email(self):
        response = self.client.post(reverse('admin_login'), {
            'username': 'admin@mystore.com',
            'password': 'AdminPassword123!'
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('admin_dashboard'))

    def test_reset_admin_password_with_email(self):
        from django.core.management import call_command
        from io import StringIO

        out = StringIO()
        call_command("reset_admin_password", username="admin@mystore.com", password="NewAdminPassword123!", stdout=out)
        self.superuser.refresh_from_db()
        self.assertTrue(self.superuser.check_password("NewAdminPassword123!"))
        self.assertTrue(self.superuser.is_staff)
        self.assertTrue(self.superuser.is_superuser)


class EmailNotificationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="buyer",
            email="buyer@example.com",
            password="Password123!"
        )

    def test_registration_emails_sent(self):
        from django.core import mail
        from web.tasks import send_registration_email, send_otp_email

        mail.outbox = []
        send_otp_email("newuser@example.com", "123456")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("123456", mail.outbox[0].body)
        self.assertEqual(mail.outbox[0].to, ["newuser@example.com"])

        mail.outbox = []
        send_registration_email("newuser@example.com", "newuser")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Welcome to MyStore", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, ["newuser@example.com"])

    def test_order_creation_emails_sent(self):
        from django.core import mail
        from web.tasks import send_order_notification, send_order_receipt_email

        cart_items = [
            {'shoeId': 1, 'shoeName': 'Test Shoe', 'shoePrice': 10000, 'quantity': 1}
        ]
        order = Order.objects.create(
            user=self.user,
            items_json=json.dumps(cart_items),
            total=10000,
            status="Pending",
            payment_method="Bank Transfer"
        )

        mail.outbox = []
        send_order_notification(order.id, order.total, "1234567890")
        self.assertEqual(len(mail.outbox), 2)
        recipients = [m.to[0] for m in mail.outbox]
        self.assertIn("buyer@example.com", recipients)

        mail.outbox = []
        send_order_receipt_email(order.id)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Order Confirmation", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, ["buyer@example.com"])

    def test_submit_order_triggers_email_tasks(self):
        from django.core import mail

        self.client.login(username="buyer", password="Password123!")
        cart_items = json.dumps([{'shoePrice': 5000, 'quantity': 2}])

        mail.outbox = []
        response = self.client.post(reverse('submit_order'), {
            'delivery_address': '123 Main St',
            'phone': '08012345678',
            'payment_method': 'Bank Transfer',
            'confirmed_account_number': '1234567890',
            'cart_json': cart_items
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 3)


class GoogleOAuthTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_google_login_url_resolution_and_redirect(self):
        google_login_url = reverse('google_login')
        self.assertEqual(google_login_url, '/accounts/google/login/')

        response = self.client.get(google_login_url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('https://accounts.google.com/o/oauth2/v2/auth'))
        self.assertIn('client_id=', response.url)

    def test_google_oauth_settings_configured(self):
        google_config = settings.SOCIALACCOUNT_PROVIDERS.get('google', {})
        self.assertIn('SCOPE', google_config)
        self.assertIn('email', google_config['SCOPE'])
        self.assertIn('profile', google_config['SCOPE'])
        self.assertIn('APP', google_config)
        self.assertIn('secret', google_config['APP'])


class MiddlewareTests(TestCase):
    @override_settings(DEBUG=True)
    def test_async_whitenoise_file_response(self):
        import asyncio
        from django.test import RequestFactory
        from web.middleware import AsyncWhiteNoiseMiddleware, AsyncWhiteNoiseFileResponse

        mw = AsyncWhiteNoiseMiddleware(lambda req: None)
        factory = RequestFactory()
        request = factory.get('/static/css/base.css')

        response = mw(request)
        self.assertIsInstance(response, AsyncWhiteNoiseFileResponse)
        self.assertTrue(hasattr(response.streaming_content, '__aiter__'))

        async def consume():
            chunks = []
            async for chunk in response:
                chunks.append(chunk)
            return chunks

        chunks = asyncio.run(consume())
        response.close()
        self.assertTrue(len(chunks) > 0)
