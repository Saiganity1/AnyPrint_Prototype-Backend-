from django.db import models


class Category(models.Model):
	name = models.CharField(max_length=80, unique=True)
	slug = models.SlugField(unique=True)

	class Meta:
		ordering = ['name']
		verbose_name_plural = 'categories'

	def __str__(self):
		return self.name


class Product(models.Model):
	name = models.CharField(max_length=120)
	slug = models.SlugField(unique=True)
	category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
	description = models.TextField()
	price = models.DecimalField(max_digits=10, decimal_places=2)
	image = models.ImageField(upload_to='products/', blank=True, null=True)
	stock_quantity = models.PositiveIntegerField(default=0)
	is_active = models.BooleanField(default=True)
	is_featured = models.BooleanField(default=False)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['-is_featured', 'name']

	def __str__(self):
		return self.name


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
	STATUS_PAID = 'PAID'
	STATUS_FAILED = 'FAILED'
	PAYMENT_STATUS_CHOICES = [
		(STATUS_PENDING, 'Pending'),
		(STATUS_PAID, 'Paid'),
		(STATUS_FAILED, 'Failed'),
	]

	full_name = models.CharField(max_length=120)
	email = models.EmailField()
	phone = models.CharField(max_length=30)
	address = models.TextField()
	payment_method = models.CharField(max_length=10, choices=PAYMENT_METHOD_CHOICES)
	notes = models.TextField(blank=True)
	total_amount = models.DecimalField(max_digits=10, decimal_places=2)
	payment_status = models.CharField(max_length=10, choices=PAYMENT_STATUS_CHOICES, default=STATUS_PENDING)
	payment_reference = models.CharField(max_length=120, blank=True)
	payment_checkout_url = models.URLField(blank=True)
	is_paid = models.BooleanField(default=False)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['-created_at']

	def __str__(self):
		return f'Order #{self.id} - {self.full_name}'


class OrderItem(models.Model):
	order = models.ForeignKey(Order, related_name='items', on_delete=models.CASCADE)
	product = models.ForeignKey(Product, on_delete=models.PROTECT)
	quantity = models.PositiveIntegerField(default=1)
	unit_price = models.DecimalField(max_digits=10, decimal_places=2)

	@property
	def subtotal(self):
		return self.quantity * self.unit_price

	def __str__(self):
		return f'{self.product.name} x {self.quantity}'
