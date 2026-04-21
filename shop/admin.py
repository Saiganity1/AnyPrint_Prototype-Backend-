from django.contrib import admin

from .models import (
	Category,
	Order,
	OrderItem,
	OrderStatusEvent,
	Product,
	ProductReview,
	ProductVariant,
	PromoCode,
	UserProfile,
	WishlistItem,
)


class OrderItemInline(admin.TabularInline):
	model = OrderItem
	extra = 0
	readonly_fields = ('product', 'variant', 'size', 'color', 'quantity', 'unit_price')


class OrderStatusEventInline(admin.TabularInline):
	model = OrderStatusEvent
	extra = 0
	readonly_fields = ('status', 'note', 'created_at')


class ProductVariantInline(admin.TabularInline):
	model = ProductVariant
	extra = 1
	fields = ('size', 'color', 'sku', 'stock_quantity', 'is_active')


class ProductReviewInline(admin.TabularInline):
	model = ProductReview
	extra = 0
	readonly_fields = ('user', 'rating', 'title', 'comment', 'created_at')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
	list_display = ('name', 'category', 'print_style', 'price', 'stock_quantity', 'is_active', 'is_featured', 'created_at')
	list_filter = ('category', 'print_style', 'is_active', 'is_featured')
	search_fields = ('name', 'description', 'print_style')
	prepopulated_fields = {'slug': ('name',)}
	inlines = [ProductVariantInline, ProductReviewInline]


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
	list_display = ('name', 'slug')
	search_fields = ('name',)
	prepopulated_fields = {'slug': ('name',)}


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
	list_display = ('product', 'size', 'color', 'sku', 'stock_quantity', 'is_active', 'created_at')
	list_filter = ('is_active', 'size', 'color', 'product__category')
	search_fields = ('product__name', 'sku', 'color')


@admin.register(ProductReview)
class ProductReviewAdmin(admin.ModelAdmin):
	list_display = ('product', 'user', 'rating', 'title', 'is_approved', 'created_at')
	list_filter = ('rating', 'is_approved', 'created_at')
	search_fields = ('product__name', 'user__username', 'title', 'comment')


@admin.register(WishlistItem)
class WishlistItemAdmin(admin.ModelAdmin):
	list_display = ('user', 'product', 'created_at')
	search_fields = ('user__username', 'product__name')


@admin.register(PromoCode)
class PromoCodeAdmin(admin.ModelAdmin):
	list_display = ('code', 'discount_type', 'value', 'active', 'usage_count', 'usage_limit', 'created_at')
	list_filter = ('discount_type', 'active', 'first_order_only')
	search_fields = ('code',)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
	list_display = ('user', 'role', 'display_name', 'updated_at')
	list_filter = ('role',)
	search_fields = ('user__username', 'user__email', 'display_name')


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
	list_display = ('id', 'tracking_number', 'full_name', 'status', 'payment_method', 'payment_status', 'total_amount', 'is_paid', 'created_at')
	list_filter = ('status', 'payment_method', 'payment_status', 'is_paid', 'created_at')
	search_fields = ('tracking_number', 'full_name', 'email', 'phone')
	inlines = [OrderItemInline, OrderStatusEventInline]
