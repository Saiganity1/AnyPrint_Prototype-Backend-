from django.contrib import admin
from .models import Category, Order, OrderItem, Product


class OrderItemInline(admin.TabularInline):
	model = OrderItem
	extra = 0
	readonly_fields = ('product', 'quantity', 'unit_price')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
	list_display = ('name', 'category', 'price', 'stock_quantity', 'is_active', 'is_featured', 'created_at')
	list_filter = ('category', 'is_active', 'is_featured')
	search_fields = ('name', 'description')
	prepopulated_fields = {'slug': ('name',)}


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
	list_display = ('name', 'slug')
	search_fields = ('name',)
	prepopulated_fields = {'slug': ('name',)}


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
	list_display = ('id', 'full_name', 'payment_method', 'payment_status', 'total_amount', 'is_paid', 'created_at')
	list_filter = ('payment_method', 'payment_status', 'is_paid', 'created_at')
	search_fields = ('full_name', 'email', 'phone')
	inlines = [OrderItemInline]
