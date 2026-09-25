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


@override_settings(DEFAULT_FILE_STORAGE='django.core.files.storage.InMemoryStorage')
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
