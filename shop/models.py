from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.db.models import Sum
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.text import slugify


class Category(models.Model):
	name = models.CharField(max_length=80, unique=True)
	slug = models.SlugField(unique=True)

	class Meta:
		ordering = ['name']
		verbose_name_plural = 'categories'

	def __str__(self):
		return self.name


class UserProfile(models.Model):
	ROLE_OWNER = 'OWNER'
	ROLE_ADMIN = 'ADMIN'
	ROLE_USER = 'USER'
	ROLE_CHOICES = [
		(ROLE_OWNER, 'Owner'),
		(ROLE_ADMIN, 'Admin'),
		(ROLE_USER, 'User'),
	]

	user = models.OneToOneField(settings.AUTH_USER_MODEL, related_name='profile', on_delete=models.CASCADE)
	role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_USER)
	display_name = models.CharField(max_length=120, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ['user__username']

	def __str__(self):
		return f'{self.user.username} ({self.get_role_display()})'

	def save(self, *args, **kwargs):
		super().save(*args, **kwargs)
		user = self.user
		is_owner = self.role == self.ROLE_OWNER
		is_admin = self.role in {self.ROLE_OWNER, self.ROLE_ADMIN}
		if user.is_superuser != is_owner or user.is_staff != is_admin:
			User.objects.filter(pk=user.pk).update(is_superuser=is_owner, is_staff=is_admin)


class Product(models.Model):
	PRINT_STYLE_CLASSIC = 'Classic'
	PRINT_STYLE_MINIMAL = 'Minimal'
	PRINT_STYLE_GRAPHIC = 'Graphic'
	PRINT_STYLE_STREET = 'Street'
	PRINT_STYLE_KIDS = 'Kids'
	PRINT_STYLE_CHOICES = [
		(PRINT_STYLE_CLASSIC, 'Classic'),
		(PRINT_STYLE_MINIMAL, 'Minimal'),
		(PRINT_STYLE_GRAPHIC, 'Graphic'),
		(PRINT_STYLE_STREET, 'Street'),
		(PRINT_STYLE_KIDS, 'Kids'),
	]

	name = models.CharField(max_length=120)
	slug = models.SlugField(unique=True)
	category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
	description = models.TextField()
	price = models.DecimalField(max_digits=10, decimal_places=2)
	print_style = models.CharField(max_length=40, choices=PRINT_STYLE_CHOICES, default=PRINT_STYLE_CLASSIC)
	image = models.ImageField(upload_to='products/', blank=True, null=True)
	stock_quantity = models.PositiveIntegerField(default=0)
	is_active = models.BooleanField(default=True)
	is_featured = models.BooleanField(default=False)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['-is_featured', 'name']
		indexes = [
			models.Index(fields=['category', 'created_at']),
			models.Index(fields=['is_active', 'is_featured']),
			models.Index(fields=['price']),
		]

	def __str__(self):
		return self.name

	def recalculate_stock(self, save=True):
		total_stock = self.variants.filter(is_active=True).aggregate(total=Sum('stock_quantity'))['total'] or 0
		if self.stock_quantity != total_stock:
			self.stock_quantity = total_stock
			if save:
				super().save(update_fields=['stock_quantity'])
		return total_stock


class ProductVariant(models.Model):
	SIZE_S = 'S'
	SIZE_M = 'M'
	SIZE_L = 'L'
	SIZE_XL = 'XL'
	SIZE_2XL = '2XL'
	SIZE_CHOICES = [
		(SIZE_S, 'Small'),
		(SIZE_M, 'Medium'),
		(SIZE_L, 'Large'),
		(SIZE_XL, 'Extra Large'),
		(SIZE_2XL, '2XL'),
	]

	product = models.ForeignKey(Product, related_name='variants', on_delete=models.CASCADE)
	size = models.CharField(max_length=4, choices=SIZE_CHOICES)
	color = models.CharField(max_length=40)
	sku = models.CharField(max_length=80, unique=True)
	stock_quantity = models.PositiveIntegerField(default=0)
	is_active = models.BooleanField(default=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['product__name', 'size', 'color']
		indexes = [
			models.Index(fields=['product', 'is_active']),
			models.Index(fields=['sku']),
		]
		constraints = [
			models.UniqueConstraint(fields=['product', 'size', 'color'], name='unique_product_variant')
		]

	def __str__(self):
		return f'{self.product.name} - {self.size} / {self.color}'

	def save(self, *args, **kwargs):
		if not self.sku:
			self.sku = slugify(f'{self.product.slug}-{self.size}-{self.color}')
		super().save(*args, **kwargs)
		self.product.recalculate_stock(save=True)

	def delete(self, *args, **kwargs):
		product = self.product
		super().delete(*args, **kwargs)
		product.recalculate_stock(save=True)


class ProductReview(models.Model):
	product = models.ForeignKey(Product, related_name='reviews', on_delete=models.CASCADE)
	user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='product_reviews', on_delete=models.CASCADE)
	rating = models.PositiveSmallIntegerField()
	title = models.CharField(max_length=120, blank=True)
	comment = models.TextField(blank=True)
	is_approved = models.BooleanField(default=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['-created_at']
		indexes = [
			models.Index(fields=['product', 'is_approved', 'created_at']),
		]
		constraints = [
			models.UniqueConstraint(fields=['product', 'user'], name='unique_product_review_per_user')
		]

	def __str__(self):
		return f'{self.product.name} review by {self.user.username}'


class WishlistItem(models.Model):
	user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='wishlist_items', on_delete=models.CASCADE)
	product = models.ForeignKey(Product, related_name='wishlist_items', on_delete=models.CASCADE)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['-created_at']
		indexes = [
			models.Index(fields=['user', 'created_at']),
		]
		constraints = [
			models.UniqueConstraint(fields=['user', 'product'], name='unique_wishlist_item')
		]

	def __str__(self):
		return f'{self.user.username} saved {self.product.name}'


class PromoCode(models.Model):
	DISCOUNT_PERCENT = 'PERCENT'
	DISCOUNT_FIXED = 'FIXED'
	DISCOUNT_CHOICES = [
		(DISCOUNT_PERCENT, 'Percent'),
		(DISCOUNT_FIXED, 'Fixed amount'),
	]

	code = models.CharField(max_length=32, unique=True)
	discount_type = models.CharField(max_length=10, choices=DISCOUNT_CHOICES, default=DISCOUNT_PERCENT)
	value = models.DecimalField(max_digits=10, decimal_places=2)
	minimum_subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
	active = models.BooleanField(default=True)
	starts_at = models.DateTimeField(null=True, blank=True)
	ends_at = models.DateTimeField(null=True, blank=True)
	usage_limit = models.PositiveIntegerField(null=True, blank=True)
	usage_count = models.PositiveIntegerField(default=0)
	first_order_only = models.BooleanField(default=False)
	applies_to_category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['code']

	def __str__(self):
		return self.code


class Order(models.Model):
	PAYMENT_COD = 'COD'
	PAYMENT_PAYMONGO = 'PAYMONGO'
	PAYMENT_STRIPE = 'STRIPE'
	PAYMENT_BANK = 'BANK'
	PAYMENT_METHOD_CHOICES = [
		(PAYMENT_COD, 'Cash on Delivery'),
		(PAYMENT_PAYMONGO, 'GCash / QR PH via PayMongo'),
		(PAYMENT_STRIPE, 'Card via Stripe'),
		(PAYMENT_BANK, 'Bank Transfer'),
	]

	STATUS_PENDING = 'PENDING'
	STATUS_CONFIRMED = 'CONFIRMED'
	STATUS_PACKED = 'PACKED'
	STATUS_SHIPPED = 'SHIPPED'
	STATUS_OUT_FOR_DELIVERY = 'OUT_FOR_DELIVERY'
	STATUS_DELIVERED = 'DELIVERED'
	STATUS_CANCELLED = 'CANCELLED'
	ORDER_STATUS_CHOICES = [
		(STATUS_PENDING, 'Pending'),
		(STATUS_CONFIRMED, 'Confirmed'),
		(STATUS_PACKED, 'Packed'),
		(STATUS_SHIPPED, 'Shipped'),
		(STATUS_OUT_FOR_DELIVERY, 'Out for delivery'),
		(STATUS_DELIVERED, 'Delivered'),
		(STATUS_CANCELLED, 'Cancelled'),
	]

	PAYMENT_STATUS_PENDING = 'PENDING'
	PAYMENT_STATUS_PAID = 'PAID'
	PAYMENT_STATUS_FAILED = 'FAILED'
	STATUS_PAID = PAYMENT_STATUS_PAID
	STATUS_FAILED = PAYMENT_STATUS_FAILED
	PAYMENT_STATUS_CHOICES = [
		(PAYMENT_STATUS_PENDING, 'Pending'),
		(PAYMENT_STATUS_PAID, 'Paid'),
		(PAYMENT_STATUS_FAILED, 'Failed'),
	]

	full_name = models.CharField(max_length=120)
	user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, related_name='orders', on_delete=models.SET_NULL)
	email = models.EmailField()
	phone = models.CharField(max_length=30)
	address = models.TextField()
	payment_method = models.CharField(max_length=10, choices=PAYMENT_METHOD_CHOICES)
	notes = models.TextField(blank=True)
	subtotal_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
	shipping_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
	discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
	bundle_discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
	total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
	promo_code = models.ForeignKey(PromoCode, null=True, blank=True, related_name='orders', on_delete=models.SET_NULL)
	status = models.CharField(max_length=20, choices=ORDER_STATUS_CHOICES, default=STATUS_PENDING)
	tracking_number = models.CharField(max_length=40, blank=True, unique=True)
	estimated_delivery_days = models.PositiveIntegerField(default=4)
	estimated_delivery_date = models.DateField(null=True, blank=True)
	payment_status = models.CharField(max_length=10, choices=PAYMENT_STATUS_CHOICES, default=PAYMENT_STATUS_PENDING)
	payment_reference = models.CharField(max_length=120, blank=True)
	idempotency_key = models.CharField(max_length=80, blank=True, null=True, unique=True, db_index=True)
	payment_checkout_url = models.URLField(blank=True)
	is_paid = models.BooleanField(default=False)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['-created_at']
		indexes = [
			models.Index(fields=['user', 'created_at']),
			models.Index(fields=['status', 'created_at']),
			models.Index(fields=['payment_status', 'created_at']),
		]

	def __str__(self):
		return f'Order #{self.id} - {self.full_name}'

	def save(self, *args, **kwargs):
		creating = self.pk is None
		super().save(*args, **kwargs)
		if creating and not self.tracking_number:
			self.tracking_number = f'AP-{self.id:06d}'
			super().save(update_fields=['tracking_number'])


class OrderItem(models.Model):
	order = models.ForeignKey(Order, related_name='items', on_delete=models.CASCADE)
	product = models.ForeignKey(Product, on_delete=models.PROTECT)
	variant = models.ForeignKey(ProductVariant, null=True, blank=True, related_name='order_items', on_delete=models.SET_NULL)
	size = models.CharField(max_length=4, blank=True)
	color = models.CharField(max_length=40, blank=True)
	quantity = models.PositiveIntegerField(default=1)
	unit_price = models.DecimalField(max_digits=10, decimal_places=2)

	class Meta:
		indexes = [
			models.Index(fields=['order', 'product']),
		]

	@property
	def subtotal(self):
		return self.quantity * self.unit_price

	def __str__(self):
		variant_label = f' ({self.size}/{self.color})' if self.size or self.color else ''
		return f'{self.product.name}{variant_label} x {self.quantity}'


class OrderStatusEvent(models.Model):
	order = models.ForeignKey(Order, related_name='status_events', on_delete=models.CASCADE)
	status = models.CharField(max_length=20, choices=Order.ORDER_STATUS_CHOICES)
	note = models.CharField(max_length=200, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['created_at']
		indexes = [
			models.Index(fields=['order', 'created_at']),
		]

	def __str__(self):
		return f'Order #{self.order_id} -> {self.status}'


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
	if not created:
		return

	role = UserProfile.ROLE_OWNER if instance.is_superuser else UserProfile.ROLE_ADMIN if instance.is_staff else UserProfile.ROLE_USER
	UserProfile.objects.get_or_create(user=instance, defaults={'role': role})
