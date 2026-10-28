from django.contrib.auth.models import AbstractUser
from django.db import models
from django.core.exceptions import ValidationError


def validate_file_size(file):
    if file.size > 2 * 1024 * 1024:
        raise ValidationError("File too large")


class User(AbstractUser):
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, unique=True, null=True, blank=True)

    groups = models.ManyToManyField(
        'auth.Group',
        related_name='shoes_users',
        blank=True,
        help_text='The groups this user belongs to.',
        verbose_name='groups',
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        related_name='shoes_user_permissions',
        blank=True,
        help_text='Specific permissions for this user.',
        verbose_name='user permissions',
    )

    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'

    def __str__(self):
        return self.username


class Category(models.Model):
    name = models.CharField(max_length=100, null=False, db_index=True)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name


class watch(models.Model):
    name = models.CharField(max_length=100, db_index=True)
    image = models.ImageField(upload_to='watchs/')
    brand = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    description = models.TextField(blank=True, null=True)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='watchs')
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0.0, db_index=True)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.0, help_text="What you paid for the item")
    discount_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Flash sale price")
    stock = models.IntegerField(default=10, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['category', 'price']),
            models.Index(fields=['brand', 'name']),
        ]

    def __str__(self):
        return f"{self.brand or ''} {self.name}".strip()


class shoe(models.Model):
    name = models.CharField(max_length=100, db_index=True)
    image = models.ImageField(upload_to='shoes/')
    brand = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    description = models.TextField(blank=True, null=True)
    AUDIENCE_CHOICES = [
        ('Male', 'Male'),
        ('Female', 'Female'),
        ('Collections', 'Collections'),
    ]
    target_audience = models.CharField(max_length=100, choices=AUDIENCE_CHOICES, default='Collections', db_index=True)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='shoes')
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0.0, db_index=True)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.0, help_text="What you paid for the item")
    discount_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Flash sale price")
    stock = models.IntegerField(default=10, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['target_audience', 'category']),
            models.Index(fields=['category', 'price']),
            models.Index(fields=['brand', 'name']),
        ]

    def __str__(self):
        return f"{self.brand or ''} {self.name}".strip()


class Product(models.Model):
    name = models.CharField(max_length=100, db_index=True)
    image = models.ImageField(upload_to='products/')
    brand = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    description = models.TextField(blank=True, null=True)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='products')
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0.0, db_index=True)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    discount_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    stock = models.IntegerField(default=10, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['category', 'created_at']),
        ]

    def __str__(self):
        return f"[{self.category.name}] {self.name}"


class OTP(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    code = models.CharField(max_length=6, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self):
        return f"OTP for {self.user.username}"


class Cart(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True, blank=True)
    session_key = models.CharField(max_length=40, null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Cart {self.id} for {self.user or self.session_key}"

    @property
    def total_price(self):
        return sum(item.total_price for item in self.items.all())


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, related_name='items', on_delete=models.CASCADE)
    shoe_item = models.ForeignKey(shoe, on_delete=models.CASCADE, null=True, blank=True)
    watch_item = models.ForeignKey(watch, on_delete=models.CASCADE, null=True, blank=True)
    product_item = models.ForeignKey(Product, on_delete=models.CASCADE, null=True, blank=True)
    quantity = models.PositiveIntegerField(default=1)

    @property
    def product(self):
        return self.shoe_item or self.watch_item or self.product_item

    @property
    def total_price(self):
        if self.product:
            p = self.product.discount_price or self.product.price
            return p * self.quantity
        return 0


class Wishlist(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    shoes = models.ManyToManyField(shoe, blank=True)
    watches = models.ManyToManyField(watch, blank=True)

    def __str__(self):
        return f"{self.user.username}'s Wishlist"


class Review(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    shoe_item = models.ForeignKey(shoe, related_name='reviews', on_delete=models.CASCADE, null=True, blank=True)
    watch_item = models.ForeignKey(watch, related_name='reviews', on_delete=models.CASCADE, null=True, blank=True)
    rating = models.IntegerField(default=5, choices=[(i, i) for i in range(1, 6)])
    comment = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self):
        prod = self.shoe_item or self.watch_item
        return f"Review by {self.user.username} on {prod}"


class Order(models.Model):
    STATUS_CHOICES = (
        ('Pending', 'Pending'),
        ('Processing', 'Processing'),
        ('Shipped', 'Shipped'),
        ('Delivered', 'Delivered'),
        ('Cancelled', 'Cancelled'),
    )
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    items_json = models.TextField(help_text='JSON serialized cart items')
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    delivery_address = models.TextField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    complete = models.BooleanField(default=False, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending', db_index=True)
    confirmed_account_number = models.CharField(max_length=20, null=True, blank=True, help_text='Account number user confirmed they paid to')
    payment_method = models.CharField(max_length=50, default='Bank Transfer')
    transaction_id = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['complete', 'status']),
        ]

    @property
    def items_list(self):
        try:
            import json
            items = json.loads(self.items_json)
            for item in items:
                item['image'] = item.get('shoeImage') or item.get('watchImage') or item.get('productImage') or item.get('image') or ''
                item['name'] = item.get('shoeName') or item.get('watchName') or item.get('productName') or item.get('name') or 'Item'
                item['id'] = item.get('shoeId') or item.get('watchId') or item.get('productId') or item.get('id')
                item['type'] = item.get('type') or ('shoe' if 'shoeId' in item else 'watch' if 'watchId' in item else 'product')
            return items
        except Exception:
            return []

    def __str__(self):
        return f"Order #{self.id} by {self.user or 'guest'} - {self.status}"

    def save(self, *args, **kwargs):
        if self.pk:
            try:
                old_order = Order.objects.get(pk=self.pk)
                if old_order.status != self.status:
                    from .tasks import send_order_status_update
                    send_order_status_update.delay(self.id, self.status)
            except Order.DoesNotExist:
                pass
        super().save(*args, **kwargs)


class Expense(models.Model):
    CATEGORY_CHOICES = [
        ('Stock', 'Stock Purchase'),
        ('Utility', 'Utility Bill'),
        ('Rent', 'Rent'),
        ('Staff', 'Staff Salary'),
        ('Marketing', 'Marketing'),
        ('Other', 'Other'),
    ]
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default='Other')
    date = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self):
        return f"{self.description} - ₦{self.amount}"


class ContactMessage(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField()
    subject = models.CharField(max_length=200)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self):
        return f"Message from {self.name} - {self.subject}"


from .banking.models import (  # noqa: E402
    BankAccountConnection,
    BankAccount,
    BankTransaction,
    BankStatement,
    BankCharge,
    ReconciliationRecord,
    BankingAuditLog,
)
