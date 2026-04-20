import json

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.db import transaction
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .models import Category, Order, OrderItem, Product
from .services import (
    PaymentGatewayError,
    create_paymongo_checkout_session,
    create_stripe_checkout_session,
)


def _build_product_payload(request, product):
    image_url = request.build_absolute_uri(product.image.url) if product.image else ''
    return {
        'id': product.id,
        'name': product.name,
        'slug': product.slug,
        'description': product.description,
        'price': str(product.price),
        'category': product.category.name if product.category else None,
        'category_slug': product.category.slug if product.category else None,
        'stock_quantity': product.stock_quantity,
        'image_url': image_url,
    }


def _restore_order_stock(order):
    for item in order.items.select_related('product'):
        product = item.product
        product.stock_quantity += item.quantity
        product.save(update_fields=['stock_quantity'])


@require_GET
def health(request):
    return JsonResponse({'ok': True, 'service': 'backend'})


@require_GET
def auth_me(request):
    if request.user.is_authenticated:
        return JsonResponse(
            {
                'is_authenticated': True,
                'user': {
                    'id': request.user.id,
                    'username': request.user.username,
                    'email': request.user.email,
                },
            }
        )

    return JsonResponse({'is_authenticated': False, 'user': None})


@csrf_exempt
@require_POST
def auth_register(request):
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON payload.'}, status=400)

    username = str(payload.get('username', '')).strip()
    email = str(payload.get('email', '')).strip()
    password = str(payload.get('password', ''))

    if not username or not password:
        return JsonResponse({'error': 'Username and password are required.'}, status=400)
    if len(password) < 8:
        return JsonResponse({'error': 'Password must be at least 8 characters.'}, status=400)
    if User.objects.filter(username=username).exists():
        return JsonResponse({'error': 'Username already exists.'}, status=400)
    if email and User.objects.filter(email=email).exists():
        return JsonResponse({'error': 'Email already exists.'}, status=400)

    user = User.objects.create_user(username=username, email=email, password=password)
    login(request, user)
    return JsonResponse(
        {
            'message': 'Registration successful.',
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
            },
        },
        status=201,
    )


@csrf_exempt
@require_POST
def auth_login(request):
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON payload.'}, status=400)

    username = str(payload.get('username', '')).strip()
    password = str(payload.get('password', ''))

    if not username or not password:
        return JsonResponse({'error': 'Username and password are required.'}, status=400)

    user = authenticate(request, username=username, password=password)
    if not user:
        return JsonResponse({'error': 'Invalid credentials.'}, status=401)

    login(request, user)
    return JsonResponse(
        {
            'message': 'Login successful.',
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
            },
        }
    )


@csrf_exempt
@require_POST
def auth_logout(request):
    logout(request)
    return JsonResponse({'message': 'Logout successful.'})


@require_GET
def category_list(request):
    categories = Category.objects.all()
    data = [
        {
            'id': category.id,
            'name': category.name,
            'slug': category.slug,
        }
        for category in categories
    ]
    return JsonResponse({'categories': data})


@require_GET
def product_list(request):
    category_slug = request.GET.get('category', '')
    products = Product.objects.filter(is_active=True)

    if category_slug:
        products = products.filter(category__slug=category_slug)

    data = [_build_product_payload(request, product) for product in products]
    return JsonResponse({'products': data})


@csrf_exempt
@require_POST
@transaction.atomic
def create_order(request):
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON payload.'}, status=400)

    required_fields = ['full_name', 'email', 'phone', 'address', 'payment_method', 'items']
    missing = [field for field in required_fields if field not in payload or not payload[field]]
    if missing:
        return JsonResponse({'error': f"Missing required fields: {', '.join(missing)}"}, status=400)

    items_payload = payload.get('items', [])
    if not isinstance(items_payload, list) or not items_payload:
        return JsonResponse({'error': 'At least one order item is required.'}, status=400)

    product_map = {}
    total = 0

    for raw_item in items_payload:
        product_id = raw_item.get('product_id')
        try:
            quantity = int(raw_item.get('quantity', 0))
        except (TypeError, ValueError):
            return JsonResponse({'error': 'Quantity must be a valid integer.'}, status=400)

        if quantity <= 0:
            return JsonResponse({'error': 'Quantity must be at least 1.'}, status=400)

        product = Product.objects.filter(id=product_id, is_active=True).first()
        if not product:
            return JsonResponse({'error': f'Product not found: {product_id}'}, status=404)
        if quantity > product.stock_quantity:
            return JsonResponse({'error': f'Insufficient stock for {product.name}. Available: {product.stock_quantity}'}, status=400)

        if product.id in product_map:
            product_map[product.id]['quantity'] += quantity
        else:
            product_map[product.id] = {'product': product, 'quantity': quantity}

    for item_data in product_map.values():
        product = item_data['product']
        quantity = item_data['quantity']
        if quantity > product.stock_quantity:
            return JsonResponse({'error': f'Insufficient stock for {product.name}. Available: {product.stock_quantity}'}, status=400)

        total += product.price * quantity

    order = Order.objects.create(
        full_name=payload['full_name'],
        email=payload['email'],
        phone=payload['phone'],
        address=payload['address'],
        payment_method=payload['payment_method'],
        notes=payload.get('notes', ''),
        total_amount=total,
        payment_status=Order.STATUS_PENDING,
        is_paid=False,
    )

    for item_data in product_map.values():
        product = item_data['product']
        quantity = item_data['quantity']
        OrderItem.objects.create(
            order=order,
            product=product,
            quantity=quantity,
            unit_price=product.price,
        )
        product.stock_quantity -= quantity
        product.save(update_fields=['stock_quantity'])

    if order.payment_method in [Order.PAYMENT_COD, Order.PAYMENT_BANK]:
        return JsonResponse(
            {
                'order_id': order.id,
                'payment_status': order.payment_status,
                'payment_method': order.payment_method,
                'redirect_url': '',
            },
            status=201,
        )

    cart_items = [
        {
            'product': item_data['product'],
            'quantity': item_data['quantity'],
        }
        for item_data in product_map.values()
    ]

    try:
        if order.payment_method == Order.PAYMENT_STRIPE:
            success_url = request.build_absolute_uri(reverse('shop:stripe_success', args=[order.id]))
            cancel_url = request.build_absolute_uri(reverse('shop:payment_cancel', args=[order.id]))
            checkout_url, reference = create_stripe_checkout_session(order, cart_items, success_url, cancel_url)
        elif order.payment_method == Order.PAYMENT_PAYMONGO:
            success_url = request.build_absolute_uri(reverse('shop:paymongo_success', args=[order.id]))
            cancel_url = request.build_absolute_uri(reverse('shop:payment_cancel', args=[order.id]))
            checkout_url, reference = create_paymongo_checkout_session(order, cart_items, success_url, cancel_url)
        else:
            _restore_order_stock(order)
            order.payment_status = Order.STATUS_FAILED
            order.save(update_fields=['payment_status'])
            return JsonResponse({'error': 'Unsupported payment method.'}, status=400)
    except PaymentGatewayError as error:
        _restore_order_stock(order)
        order.payment_status = Order.STATUS_FAILED
        order.save(update_fields=['payment_status'])
        return JsonResponse({'error': str(error)}, status=400)

    order.payment_reference = reference
    order.payment_checkout_url = checkout_url
    order.save(update_fields=['payment_reference', 'payment_checkout_url'])

    return JsonResponse(
        {
            'order_id': order.id,
            'payment_status': order.payment_status,
            'payment_method': order.payment_method,
            'redirect_url': checkout_url,
        },
        status=201,
    )
