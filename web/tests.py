import json
from io import BytesIO
from PIL import Image
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from .models import User, Category, shoe, watch, Cart, CartItem, Order, ContactMessage


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

        # Short Render database hostname
        short_url = "postgres://user:pass@dpg-db2hhvui0phs73enh0o0-a/drop_db"
        formatted = format_render_database_url(short_url)
        self.assertEqual(formatted, "postgres://user:pass@dpg-db2hhvui0phs73enh0o0-a.oregon-postgres.render.com/drop_db")

        # Already formatted Render database hostname
        full_url = "postgres://user:pass@dpg-db2hhvui0phs73enh0o0-a.oregon-postgres.render.com/drop_db"
        self.assertEqual(format_render_database_url(full_url), full_url)

        # Standard non-Render hostname
        local_url = "postgres://postgres:postgres@127.0.0.1:5432/my_store_db"
        self.assertEqual(format_render_database_url(local_url), local_url)

        # Empty URL
        self.assertEqual(format_render_database_url(""), "")


class AdminPasswordResetTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_reset_admin_password_management_command(self):
        from django.core.management import call_command
        from io import StringIO

        out = StringIO()
        # Reset password for existing user or create
        call_command("reset_admin_password", username="admin_test", password="NewPassword123!", email="admin@test.com", stdout=out)
        user = User.objects.get(username="admin_test")
        self.assertTrue(user.check_password("NewPassword123!"))
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)

        # Reset password again
        call_command("reset_admin_password", username="admin_test", password="UpdatedPassword123!", stdout=out)
        user.refresh_from_db()
        self.assertTrue(user.check_password("UpdatedPassword123!"))

    def test_password_reset_views_status_code(self):
        response = self.client.get(reverse('password_reset'))
        self.assertEqual(response.status_code, 200)

        response = self.client.get(reverse('password_reset_done'))
        self.assertEqual(response.status_code, 200)
