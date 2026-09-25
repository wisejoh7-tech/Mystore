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
