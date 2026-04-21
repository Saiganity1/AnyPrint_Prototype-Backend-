import json
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.core.paginator import EmptyPage, Paginator
from django.db import transaction
from django.db.models import Avg, Count, Q, Sum
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

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
from .services import (
    PaymentGatewayError,
    create_paymongo_checkout_session,
    create_stripe_checkout_session,
)


def _build_product_payload(request, product, wishlist_ids=None, detail=False):
    return _serialize_product_payload(request, product, wishlist_ids=wishlist_ids, detail=detail)


def _parse_positive_int(value, default, minimum, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default

    if parsed < minimum:
        return minimum
    if parsed > maximum:
        return maximum
    return parsed


def _serialize_order_item(item):
    return {
        'product_id': item.product_id,
        'product_name': item.product.name,
        'product_slug': item.product.slug,
        'quantity': item.quantity,
        'unit_price': str(item.unit_price),
        'subtotal': str(item.subtotal),
    }


def _serialize_order(order):
    return {
        'id': order.id,
        'full_name': order.full_name,
        'email': order.email,
        'phone': order.phone,
        'address': order.address,
        'payment_method': order.payment_method,
        'payment_status': order.payment_status,
        'total_amount': str(order.total_amount),
        'notes': order.notes,
        'created_at': order.created_at.isoformat(),
        'items': [_serialize_order_item(item) for item in order.items.select_related('product').all()],
    }


def _normalize_text(value):
    return str(value or '').strip()


def _parse_decimal(value, default=Decimal('0.00')):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def _money_string(value):
    return f'{_parse_decimal(value):.2f}'


def _get_or_create_profile(user):
    profile, _created = UserProfile.objects.get_or_create(user=user)
    return profile


def _get_user_role(user):
    if not user or not user.is_authenticated:
        return UserProfile.ROLE_USER

    if user.is_superuser:
        return UserProfile.ROLE_OWNER
    if user.is_staff:
        return UserProfile.ROLE_ADMIN

    profile = getattr(user, 'profile', None)
    if profile:
        return profile.role

    return UserProfile.ROLE_USER


def _serialize_user(user):
    profile = _get_or_create_profile(user)
    return {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'role': profile.role,
        'role_label': profile.get_role_display(),
        'is_staff': user.is_staff,
        'is_superuser': user.is_superuser,
    }


def _serialize_variant(variant):
    return {
        'id': variant.id,
        'size': variant.size,
        'size_label': variant.get_size_display(),
        'color': variant.color,
        'stock_quantity': variant.stock_quantity,
        'sku': variant.sku,
        'is_active': variant.is_active,
    }


def _serialize_review(review):
    return {
        'id': review.id,
        'user_id': review.user_id,
        'username': review.user.username,
        'rating': review.rating,
        'title': review.title,
        'comment': review.comment,
        'created_at': review.created_at.isoformat(),
    }


def _serialize_order_event(event):
    return {
        'status': event.status,
        'note': event.note,
        'created_at': event.created_at.isoformat(),
    }


def _default_colors_for_product(product):
    style = (product.print_style or '').lower()
    category_name = (product.category.name if product.category else '').lower()

    if 'graphic' in style or 'graphic' in category_name:
        return ['Black', 'Cream', 'Navy']
    if 'kids' in style or 'kids' in category_name:
        return ['White', 'Sky', 'Mint']
    if 'street' in style or 'oversized' in category_name:
        return ['Black', 'Sand', 'Olive']
    if 'minimal' in style:
        return ['Black', 'White', 'Stone']
    return ['Black', 'White', 'Sand']


def _variant_payloads_for_product(product):
    active_variants = list(product.variants.filter(is_active=True).order_by('size', 'color'))
    if active_variants:
        return [_serialize_variant(variant) for variant in active_variants]

    size_codes = [choice[0] for choice in ProductVariant.SIZE_CHOICES[:4]]
    color_codes = _default_colors_for_product(product)
    combinations = [(size_code, color_code) for size_code in size_codes for color_code in color_codes]
    total_stock = int(product.stock_quantity or 0)
    base_stock = total_stock // len(combinations) if combinations else 0
    remainder = total_stock % len(combinations) if combinations else 0
    payloads = []

    for index, (size_code, color_code) in enumerate(combinations):
        stock_quantity = base_stock + (1 if index < remainder else 0)
        payloads.append(
            {
                'id': None,
                'size': size_code,
                'size_label': dict(ProductVariant.SIZE_CHOICES).get(size_code, size_code),
                'color': color_code,
                'stock_quantity': stock_quantity,
                'sku': '',
                'is_active': True,
                'synthetic': True,
            }
        )

    return payloads


def _product_rating_summary(product):
    aggregate = product.reviews.filter(is_approved=True).aggregate(average=Avg('rating'), total=Count('id'))
    return {
        'average_rating': float(aggregate['average']) if aggregate['average'] is not None else None,
        'review_count': aggregate['total'] or 0,
    }


def _wishlist_product_ids(user):
    if not user or not user.is_authenticated:
        return set()

    return set(WishlistItem.objects.filter(user=user).values_list('product_id', flat=True))


def _product_selection_lists(variants):
    sizes = []
    colors = []
    for variant in variants:
        if variant['size'] not in sizes:
            sizes.append(variant['size'])
        if variant['color'] not in colors:
            colors.append(variant['color'])
    return sizes, colors


def _serialize_product_payload(request, product, *, wishlist_ids=None, detail=False):
    rating_summary = _product_rating_summary(product)
    variant_payloads = _variant_payloads_for_product(product)
    available_sizes, available_colors = _product_selection_lists(variant_payloads)
    is_saved = bool(wishlist_ids and product.id in wishlist_ids)

    payload = {
        'id': product.id,
        'name': product.name,
        'slug': product.slug,
        'description': product.description,
        'price': _money_string(product.price),
        'category': product.category.name if product.category else None,
        'category_slug': product.category.slug if product.category else None,
        'print_style': product.print_style,
        'stock_quantity': product.stock_quantity,
        'image_url': request.build_absolute_uri(product.image.url) if product.image else '',
        'is_featured': product.is_featured,
        'average_rating': rating_summary['average_rating'],
        'review_count': rating_summary['review_count'],
        'variants': variant_payloads,
        'available_sizes': available_sizes,
        'available_colors': available_colors,
        'wishlist_saved': is_saved,
    }

    if detail:
        reviews = [
            _serialize_review(review)
            for review in product.reviews.select_related('user').filter(is_approved=True).order_by('-created_at')[:12]
        ]
        related_products = [
            _serialize_product_payload(request, item, wishlist_ids=wishlist_ids)
            for item in Product.objects.filter(is_active=True)
            .exclude(pk=product.pk)
            .filter(Q(category=product.category) | Q(print_style=product.print_style))
            .select_related('category')
            .order_by('-is_featured', 'name')[:4]
        ]
        frequently_bought_together = [
            _serialize_product_payload(request, item, wishlist_ids=wishlist_ids)
            for item in Product.objects.filter(is_active=True)
            .exclude(pk=product.pk)
            .select_related('category')
            .order_by('-stock_quantity', '-is_featured', 'name')[:4]
        ]
        payload.update(
            {
                'reviews': reviews,
                'related_products': related_products,
                'frequently_bought_together': frequently_bought_together,
            }
        )

    return payload


def _serialize_order_item_detail(item):
    return {
        'product_id': item.product_id,
        'product_name': item.product.name,
        'product_slug': item.product.slug,
        'variant_id': item.variant_id,
        'size': item.size,
        'color': item.color,
        'quantity': item.quantity,
        'unit_price': _money_string(item.unit_price),
        'subtotal': _money_string(item.subtotal),
    }


def _serialize_order_detail(order):
    status_events = [
        _serialize_order_event(event)
        for event in order.status_events.all().order_by('created_at')
    ]
    return {
        'id': order.id,
        'tracking_number': order.tracking_number,
        'full_name': order.full_name,
        'email': order.email,
        'phone': order.phone,
        'address': order.address,
        'payment_method': order.payment_method,
        'payment_status': order.payment_status,
        'status': order.status,
        'subtotal_amount': _money_string(order.subtotal_amount),
        'shipping_fee': _money_string(order.shipping_fee),
        'discount_amount': _money_string(order.discount_amount),
        'bundle_discount_amount': _money_string(order.bundle_discount_amount),
        'total_amount': _money_string(order.total_amount),
        'notes': order.notes,
        'promo_code': order.promo_code.code if order.promo_code else '',
        'estimated_delivery_days': order.estimated_delivery_days,
        'estimated_delivery_date': order.estimated_delivery_date.isoformat() if order.estimated_delivery_date else '',
        'payment_reference': order.payment_reference,
        'payment_checkout_url': order.payment_checkout_url,
        'tracking_events': status_events,
        'items': [_serialize_order_item_detail(item) for item in order.items.select_related('product', 'variant').all()],
        'created_at': order.created_at.isoformat(),
    }


def _require_roles(request, allowed_roles):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required.'}, status=401)

    role = _get_user_role(request.user)
    if role not in allowed_roles:
        return JsonResponse({'error': 'Permission denied.'}, status=403)

    return None


def _restore_order_stock(order):
    for item in order.items.select_related('product', 'variant'):
        if item.variant:
            item.variant.stock_quantity += item.quantity
            item.variant.save(update_fields=['stock_quantity'])
        else:
            item.product.stock_quantity += item.quantity
            item.product.save(update_fields=['stock_quantity'])


def _bundle_discount(subtotal, total_quantity):
    if total_quantity >= 9:
        rate = Decimal('0.15')
    elif total_quantity >= 5:
        rate = Decimal('0.10')
    elif total_quantity >= 3:
        rate = Decimal('0.05')
    else:
        rate = Decimal('0.00')

    return (subtotal * rate).quantize(Decimal('0.01'))


def _shipping_quote(address, subtotal_after_discounts):
    address_text = _normalize_text(address).lower()
    metro_markers = [
        'metro manila',
        'ncr',
        'manila',
        'quezon city',
        'makati',
        'pasig',
        'taguig',
        'mandaluyong',
        'pasay',
        'caloocan',
    ]

    if subtotal_after_discounts >= Decimal('2000'):
        return {
            'shipping_fee': Decimal('0.00'),
            'estimated_delivery_days': 2,
            'delivery_tier': 'free',
            'delivery_eta_text': '2-3 days',
        }

    if any(marker in address_text for marker in metro_markers):
        return {
            'shipping_fee': Decimal('85.00'),
            'estimated_delivery_days': 3,
            'delivery_tier': 'metro',
            'delivery_eta_text': '2-4 days',
        }

    return {
        'shipping_fee': Decimal('130.00'),
        'estimated_delivery_days': 5,
        'delivery_tier': 'nationwide',
        'delivery_eta_text': '4-7 days',
    }


def _resolve_variant_entry(item_payload):
    product_id = item_payload.get('product_id')
    variant_id = item_payload.get('variant_id')
    size = _normalize_text(item_payload.get('size'))
    color = _normalize_text(item_payload.get('color'))

    try:
        quantity = int(item_payload.get('quantity', 0))
    except (TypeError, ValueError):
        return None, 'Quantity must be a valid integer.'

    if quantity <= 0:
        return None, 'Quantity must be at least 1.'

    if variant_id:
        variant = ProductVariant.objects.select_related('product', 'product__category').filter(
            id=variant_id,
            is_active=True,
            product__is_active=True,
        ).first()
        if not variant:
            return None, f'Variant not found: {variant_id}'
        product = variant.product
        if product_id and int(product_id) != product.id:
            return None, 'Variant does not belong to the selected product.'
        return (
            {
                'product': product,
                'variant': variant,
                'quantity': quantity,
                'size': variant.size,
                'color': variant.color,
                'unit_price': product.price,
            },
            '',
        )

    if not product_id:
        return None, 'Product is required.'

    product = Product.objects.select_related('category').filter(id=product_id, is_active=True).first()
    if not product:
        return None, f'Product not found: {product_id}'

    variant = None
    if size or color:
        variant_queryset = product.variants.filter(is_active=True)
        if size:
            variant_queryset = variant_queryset.filter(size=size)
        if color:
            variant_queryset = variant_queryset.filter(color__iexact=color)
        variant = variant_queryset.first()

    if not variant and product.variants.filter(is_active=True).exists():
        variant = product.variants.filter(is_active=True).order_by('size', 'color').first()

    if variant:
        return (
            {
                'product': product,
                'variant': variant,
                'quantity': quantity,
                'size': variant.size,
                'color': variant.color,
                'unit_price': product.price,
            },
            '',
        )

    return (
        {
            'product': product,
            'variant': None,
            'quantity': quantity,
            'size': size,
            'color': color,
            'unit_price': product.price,
        },
        '',
    )


def _resolve_cart_items(items_payload):
    resolved_items = []
    for raw_item in items_payload:
        resolved_item, error = _resolve_variant_entry(raw_item)
        if error:
            return None, error

        key = resolved_item['variant'].id if resolved_item['variant'] else f"{resolved_item['product'].id}:{resolved_item['size']}:{resolved_item['color']}"
        existing_item = next((item for item in resolved_items if item['key'] == key), None)
        if existing_item:
            existing_item['quantity'] += resolved_item['quantity']
            continue

        resolved_item['key'] = key
        resolved_items.append(resolved_item)

    for item in resolved_items:
        stock_quantity = item['variant'].stock_quantity if item['variant'] else item['product'].stock_quantity
        if item['quantity'] > stock_quantity:
            return None, f'Insufficient stock for {item["product"].name}. Available: {stock_quantity}'

    return resolved_items, ''


def _validate_promo_code(promo_code_value, subtotal, resolved_items, user):
    promo_code_text = _normalize_text(promo_code_value)
    if not promo_code_text:
        return None, Decimal('0.00'), ''

    promo = PromoCode.objects.select_related('applies_to_category').filter(code__iexact=promo_code_text).first()
    if not promo:
        return None, Decimal('0.00'), 'Promo code not found.'
    if not promo.active:
        return None, Decimal('0.00'), 'Promo code is inactive.'
    if promo.starts_at and timezone.now() < promo.starts_at:
        return None, Decimal('0.00'), 'Promo code is not active yet.'
    if promo.ends_at and timezone.now() > promo.ends_at:
        return None, Decimal('0.00'), 'Promo code has expired.'
    if promo.usage_limit is not None and promo.usage_count >= promo.usage_limit:
        return None, Decimal('0.00'), 'Promo code usage limit reached.'
    if promo.minimum_subtotal and subtotal < promo.minimum_subtotal:
        return None, Decimal('0.00'), f'Minimum subtotal for this promo is {_money_string(promo.minimum_subtotal)}.'
    if promo.first_order_only and user and user.is_authenticated and Order.objects.filter(user=user).exists():
        return None, Decimal('0.00'), 'Promo code is only valid on the first order.'

    applicable_subtotal = subtotal
    if promo.applies_to_category:
        applicable_subtotal = sum(
            item['unit_price'] * item['quantity']
            for item in resolved_items
            if item['product'].category_id == promo.applies_to_category_id
        )

    if promo.discount_type == PromoCode.DISCOUNT_PERCENT:
        promo_discount = (applicable_subtotal * (promo.value / Decimal('100'))).quantize(Decimal('0.01'))
    else:
        promo_discount = min(promo.value, applicable_subtotal).quantize(Decimal('0.01'))

    return promo, promo_discount, ''


def _build_checkout_quote(payload, user=None):
    items_payload = payload.get('items', [])
    if not isinstance(items_payload, list) or not items_payload:
        return None, 'At least one order item is required.'

    resolved_items, error = _resolve_cart_items(items_payload)
    if error:
        return None, error

    subtotal = sum((item['unit_price'] * item['quantity'] for item in resolved_items), Decimal('0.00')).quantize(Decimal('0.01'))
    total_quantity = sum(item['quantity'] for item in resolved_items)
    bundle_discount = _bundle_discount(subtotal, total_quantity)
    promo, promo_discount, promo_error = _validate_promo_code(payload.get('promo_code', ''), subtotal - bundle_discount, resolved_items, user)
    if promo_error:
        return None, promo_error

    discount_amount = (bundle_discount + promo_discount).quantize(Decimal('0.01'))
    subtotal_after_discounts = (subtotal - discount_amount).quantize(Decimal('0.01'))
    shipping_quote = _shipping_quote(payload.get('address', ''), subtotal_after_discounts)
    total_amount = (subtotal_after_discounts + shipping_quote['shipping_fee']).quantize(Decimal('0.01'))

    return {
        'resolved_items': resolved_items,
        'subtotal_amount': subtotal,
        'bundle_discount_amount': bundle_discount,
        'promo_discount_amount': promo_discount,
        'discount_amount': discount_amount,
        'shipping_fee': shipping_quote['shipping_fee'],
        'estimated_delivery_days': shipping_quote['estimated_delivery_days'],
        'delivery_eta_text': shipping_quote['delivery_eta_text'],
        'total_amount': total_amount,
        'promo': promo,
    }, ''


def _set_order_status(order, status, note=''):
    order.status = status
    order.save(update_fields=['status'])
    OrderStatusEvent.objects.create(order=order, status=status, note=note)


@ensure_csrf_cookie
@require_GET
def health(request):
    return JsonResponse({'ok': True, 'service': 'backend'})


@ensure_csrf_cookie
@require_GET
def auth_me(request):
    if request.user.is_authenticated:
        profile = _get_or_create_profile(request.user)
        return JsonResponse(
            {
                'is_authenticated': True,
                'user': _serialize_user(request.user),
                'role': profile.role,
            }
        )

    return JsonResponse({'is_authenticated': False, 'user': None})


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
    _get_or_create_profile(user)
    login(request, user)
    return JsonResponse(
        {
            'message': 'Registration successful.',
            'user': _serialize_user(user),
        },
        status=201,
    )


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
            'user': _serialize_user(user),
        }
    )


@require_POST
def auth_logout(request):
    logout(request)
    return JsonResponse({'message': 'Logout successful.'})


@ensure_csrf_cookie
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


@ensure_csrf_cookie
@require_GET
def product_list(request):
    category_slug = request.GET.get('category', '')
    search = str(request.GET.get('search', '')).strip()
    sort = str(request.GET.get('sort', 'featured')).strip()
    size = _normalize_text(request.GET.get('size', ''))
    color = _normalize_text(request.GET.get('color', ''))
    print_style = _normalize_text(request.GET.get('print_style', ''))
    min_price = _parse_decimal(request.GET.get('min_price', '0'), Decimal('0.00'))
    max_price_raw = _normalize_text(request.GET.get('max_price', ''))
    max_price = _parse_decimal(max_price_raw, Decimal('0.00')) if max_price_raw else None
    page_number = _parse_positive_int(request.GET.get('page', 1), 1, 1, 100000)
    page_size = _parse_positive_int(request.GET.get('page_size', 12), 12, 1, 48)

    products = Product.objects.filter(is_active=True).select_related('category').prefetch_related('variants', 'reviews')

    if category_slug:
        products = products.filter(category__slug=category_slug)

    if search:
        products = products.filter(
            Q(name__icontains=search)
            | Q(description__icontains=search)
            | Q(category__name__icontains=search)
            | Q(category__slug__icontains=search)
        )

    if size:
        products = products.filter(variants__size=size)

    if color:
        products = products.filter(variants__color__iexact=color)

    if print_style:
        products = products.filter(print_style__iexact=print_style)

    if min_price:
        products = products.filter(price__gte=min_price)

    if max_price is not None and max_price > 0:
        products = products.filter(price__lte=max_price)

    sort_map = {
        'featured': ['-is_featured', 'name'],
        'name': ['name'],
        '-name': ['-name'],
        'price': ['price', 'name'],
        '-price': ['-price', 'name'],
        'newest': ['-created_at'],
        'stock': ['stock_quantity', 'name'],
        '-stock': ['-stock_quantity', 'name'],
    }
    products = products.order_by(*sort_map.get(sort, ['-is_featured', 'name']))
    if size or color:
        products = products.distinct()

    wishlist_ids = _wishlist_product_ids(request.user)

    paginator = Paginator(products, page_size)
    try:
        page = paginator.page(page_number)
    except EmptyPage:
        page = paginator.page(paginator.num_pages or 1)

    data = [_build_product_payload(request, product, wishlist_ids=wishlist_ids) for product in page.object_list]
    return JsonResponse(
        {
            'products': data,
            'pagination': {
                'page': page.number,
                'page_size': page_size,
                'total_pages': paginator.num_pages,
                'total_items': paginator.count,
                'has_next': page.has_next(),
                'has_previous': page.has_previous(),
            },
        }
    )


@require_GET
def product_detail(request, slug):
    product = Product.objects.filter(is_active=True, slug=slug).first()
    if not product:
        return JsonResponse({'error': 'Product not found.'}, status=404)

    wishlist_ids = _wishlist_product_ids(request.user)
    return JsonResponse({'product': _build_product_payload(request, product, wishlist_ids=wishlist_ids, detail=True)})


@require_GET
def product_detail_by_id(request, product_id):
    product = Product.objects.filter(is_active=True, id=product_id).first()
    if not product:
        return JsonResponse({'error': 'Product not found.'}, status=404)

    wishlist_ids = _wishlist_product_ids(request.user)
    return JsonResponse({'product': _build_product_payload(request, product, wishlist_ids=wishlist_ids, detail=True)})


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

    quote, error = _build_checkout_quote(payload, request.user)
    if error:
        return JsonResponse({'error': error}, status=400)

    payment_method = _normalize_text(payload.get('payment_method'))
    if payment_method not in dict(Order.PAYMENT_METHOD_CHOICES):
        return JsonResponse({'error': 'Unsupported payment method.'}, status=400)

    promo = quote['promo']
    if promo:
        promo.usage_count += 1
        promo.save(update_fields=['usage_count'])

    order = Order.objects.create(
        user=request.user if request.user.is_authenticated else None,
        full_name=_normalize_text(payload.get('full_name')),
        email=_normalize_text(payload.get('email')),
        phone=_normalize_text(payload.get('phone')),
        address=_normalize_text(payload.get('address')),
        payment_method=payment_method,
        notes=_normalize_text(payload.get('notes')),
        subtotal_amount=quote['subtotal_amount'],
        shipping_fee=quote['shipping_fee'],
        discount_amount=quote['discount_amount'],
        bundle_discount_amount=quote['bundle_discount_amount'],
        total_amount=quote['total_amount'],
        promo_code=promo,
        status=Order.STATUS_PENDING,
        estimated_delivery_days=quote['estimated_delivery_days'],
        estimated_delivery_date=timezone.localdate() + timedelta(days=quote['estimated_delivery_days']),
        payment_status=Order.PAYMENT_STATUS_PENDING,
        is_paid=False,
    )

    gateway_items = []
    for item in quote['resolved_items']:
        order_item = OrderItem.objects.create(
            order=order,
            product=item['product'],
            variant=item['variant'],
            size=item['size'],
            color=item['color'],
            quantity=item['quantity'],
            unit_price=item['unit_price'],
        )
        gateway_items.append({'product': item['product'], 'quantity': item['quantity']})

        if item['variant']:
            item['variant'].stock_quantity -= item['quantity']
            item['variant'].save(update_fields=['stock_quantity'])
        else:
            item['product'].stock_quantity -= item['quantity']
            item['product'].save(update_fields=['stock_quantity'])

    OrderStatusEvent.objects.create(order=order, status=Order.STATUS_PENDING, note='Order created.')

    if order.payment_method in [Order.PAYMENT_COD, Order.PAYMENT_BANK]:
        return JsonResponse(
            {
                'order_id': order.id,
                'tracking_number': order.tracking_number,
                'payment_status': order.payment_status,
                'payment_method': order.payment_method,
                'status': order.status,
                'redirect_url': '',
                'quote': {
                    'subtotal_amount': _money_string(order.subtotal_amount),
                    'shipping_fee': _money_string(order.shipping_fee),
                    'discount_amount': _money_string(order.discount_amount),
                    'bundle_discount_amount': _money_string(order.bundle_discount_amount),
                    'total_amount': _money_string(order.total_amount),
                    'estimated_delivery_days': order.estimated_delivery_days,
                    'estimated_delivery_date': order.estimated_delivery_date.isoformat() if order.estimated_delivery_date else '',
                },
            },
            status=201,
        )

    try:
        if order.payment_method == Order.PAYMENT_STRIPE:
            success_url = request.build_absolute_uri(reverse('shop:stripe_success', args=[order.id]))
            cancel_url = request.build_absolute_uri(reverse('shop:payment_cancel', args=[order.id]))
            checkout_url, reference = create_stripe_checkout_session(order, gateway_items, success_url, cancel_url)
        elif order.payment_method == Order.PAYMENT_PAYMONGO:
            success_url = request.build_absolute_uri(reverse('shop:paymongo_success', args=[order.id]))
            cancel_url = request.build_absolute_uri(reverse('shop:payment_cancel', args=[order.id]))
            checkout_url, reference = create_paymongo_checkout_session(order, gateway_items, success_url, cancel_url)
        else:
            _restore_order_stock(order)
            order.payment_status = Order.PAYMENT_STATUS_FAILED
            order.status = Order.STATUS_CANCELLED
            order.save(update_fields=['payment_status', 'status'])
            OrderStatusEvent.objects.create(order=order, status=Order.STATUS_CANCELLED, note='Unsupported payment method.')
            return JsonResponse({'error': 'Unsupported payment method.'}, status=400)
    except PaymentGatewayError as error:
        _restore_order_stock(order)
        order.payment_status = Order.PAYMENT_STATUS_FAILED
        order.status = Order.STATUS_CANCELLED
        order.save(update_fields=['payment_status', 'status'])
        OrderStatusEvent.objects.create(order=order, status=Order.STATUS_CANCELLED, note=str(error))
        return JsonResponse({'error': str(error)}, status=400)

    order.payment_reference = reference
    order.payment_checkout_url = checkout_url
    order.save(update_fields=['payment_reference', 'payment_checkout_url'])

    return JsonResponse(
        {
            'order_id': order.id,
            'tracking_number': order.tracking_number,
            'payment_status': order.payment_status,
            'payment_method': order.payment_method,
            'status': order.status,
            'redirect_url': checkout_url,
            'quote': {
                'subtotal_amount': _money_string(order.subtotal_amount),
                'shipping_fee': _money_string(order.shipping_fee),
                'discount_amount': _money_string(order.discount_amount),
                'bundle_discount_amount': _money_string(order.bundle_discount_amount),
                'total_amount': _money_string(order.total_amount),
                'estimated_delivery_days': order.estimated_delivery_days,
                'estimated_delivery_date': order.estimated_delivery_date.isoformat() if order.estimated_delivery_date else '',
            },
        },
        status=201,
    )


@ensure_csrf_cookie
@require_GET
def order_history(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required.'}, status=401)

    orders = (
        Order.objects.filter(user=request.user)
        .select_related('promo_code')
        .prefetch_related('items__product', 'items__variant', 'status_events')
        .order_by('-created_at')
    )

    return JsonResponse(
        {
            'orders': [_serialize_order_detail(order) for order in orders],
            'count': orders.count(),
        }
    )


@ensure_csrf_cookie
@require_POST
def checkout_quote(request):
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON payload.'}, status=400)

    quote, error = _build_checkout_quote(payload, request.user)
    if error:
        return JsonResponse({'error': error}, status=400)

    return JsonResponse(
        {
            'quote': {
                'subtotal_amount': _money_string(quote['subtotal_amount']),
                'shipping_fee': _money_string(quote['shipping_fee']),
                'discount_amount': _money_string(quote['discount_amount']),
                'bundle_discount_amount': _money_string(quote['bundle_discount_amount']),
                'promo_discount_amount': _money_string(quote['promo_discount_amount']),
                'total_amount': _money_string(quote['total_amount']),
                'estimated_delivery_days': quote['estimated_delivery_days'],
                'delivery_eta_text': quote['delivery_eta_text'],
                'estimated_delivery_date': (timezone.localdate() + timedelta(days=quote['estimated_delivery_days'])).isoformat(),
            }
        }
    )


@ensure_csrf_cookie
@require_GET
def product_reviews(request, slug):
    product = Product.objects.filter(is_active=True, slug=slug).first()
    if not product:
        return JsonResponse({'error': 'Product not found.'}, status=404)

    if request.method == 'GET':
        reviews = product.reviews.select_related('user').filter(is_approved=True).order_by('-created_at')
        return JsonResponse(
            {
                'product': {
                    'id': product.id,
                    'slug': product.slug,
                    'average_rating': _product_rating_summary(product)['average_rating'],
                    'review_count': _product_rating_summary(product)['review_count'],
                },
                'reviews': [_serialize_review(review) for review in reviews],
            }
        )

    return JsonResponse({'error': 'Unsupported method.'}, status=405)


@require_POST
@transaction.atomic
def product_reviews_create(request, slug):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required.'}, status=401)

    product = Product.objects.filter(is_active=True, slug=slug).first()
    if not product:
        return JsonResponse({'error': 'Product not found.'}, status=404)

    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON payload.'}, status=400)

    try:
        rating = int(payload.get('rating', 0))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Rating must be a number.'}, status=400)

    if rating < 1 or rating > 5:
        return JsonResponse({'error': 'Rating must be between 1 and 5.'}, status=400)

    review, _created = ProductReview.objects.update_or_create(
        product=product,
        user=request.user,
        defaults={
            'rating': rating,
            'title': _normalize_text(payload.get('title')),
            'comment': _normalize_text(payload.get('comment')),
            'is_approved': True,
        },
    )

    summary = _product_rating_summary(product)
    return JsonResponse(
        {
            'message': 'Review saved.',
            'review': _serialize_review(review),
            'summary': summary,
        },
        status=201,
    )


@ensure_csrf_cookie
@require_GET
def wishlist_list(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required.'}, status=401)

    items = (
        WishlistItem.objects.filter(user=request.user)
        .select_related('product', 'product__category')
        .order_by('-created_at')
    )
    wishlist_ids = {item.product_id for item in items}

    return JsonResponse(
        {
            'items': [
                {
                    'id': item.id,
                    'product': _build_product_payload(request, item.product, wishlist_ids=wishlist_ids, detail=False),
                    'created_at': item.created_at.isoformat(),
                }
                for item in items
            ],
            'count': items.count(),
        }
    )


@require_POST
@transaction.atomic
def wishlist_toggle(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required.'}, status=401)

    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON payload.'}, status=400)

    product_id = payload.get('product_id')
    product = Product.objects.filter(id=product_id, is_active=True).first()
    if not product:
        return JsonResponse({'error': 'Product not found.'}, status=404)

    wishlist_item = WishlistItem.objects.filter(user=request.user, product=product).first()
    saved = False
    if wishlist_item:
        wishlist_item.delete()
    else:
        WishlistItem.objects.create(user=request.user, product=product)
        saved = True

    return JsonResponse({'product_id': product.id, 'saved': saved, 'count': WishlistItem.objects.filter(user=request.user).count()})


@ensure_csrf_cookie
@require_GET
def order_track(request):
    tracking_number = _normalize_text(request.GET.get('tracking_number'))
    order_id = _normalize_text(request.GET.get('order_id'))
    email = _normalize_text(request.GET.get('email'))

    order = None
    if tracking_number:
        order = Order.objects.select_related('user', 'promo_code').prefetch_related('items__product', 'items__variant', 'status_events').filter(tracking_number=tracking_number).first()
    elif order_id:
        try:
            order = Order.objects.select_related('user', 'promo_code').prefetch_related('items__product', 'items__variant', 'status_events').filter(id=int(order_id)).first()
        except (TypeError, ValueError):
            return JsonResponse({'error': 'Invalid order ID.'}, status=400)

    if not order:
        return JsonResponse({'error': 'Order not found.'}, status=404)

    if request.user.is_authenticated:
        role = _get_user_role(request.user)
        if role not in {UserProfile.ROLE_OWNER, UserProfile.ROLE_ADMIN} and order.user_id and order.user_id != request.user.id:
            return JsonResponse({'error': 'Permission denied.'}, status=403)
    elif email and order.email.lower() != email.lower():
        return JsonResponse({'error': 'Order email does not match.'}, status=403)

    return JsonResponse({'order': _serialize_order_detail(order)})


@ensure_csrf_cookie
@require_GET
def admin_dashboard(request):
    role_error = _require_roles(request, {UserProfile.ROLE_OWNER, UserProfile.ROLE_ADMIN})
    if role_error:
        return role_error

    total_orders = Order.objects.count()
    paid_orders = Order.objects.filter(is_paid=True).count()
    total_sales = Order.objects.filter(is_paid=True).aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    low_stock_products = Product.objects.filter(is_active=True, stock_quantity__lte=5).select_related('category').order_by('stock_quantity', 'name')
    low_stock_variants = ProductVariant.objects.filter(is_active=True, stock_quantity__lte=5).select_related('product', 'product__category').order_by('stock_quantity', 'product__name')
    top_products = (
        OrderItem.objects.values('product_id', 'product__name', 'product__slug')
        .annotate(quantity_sold=Sum('quantity'))
        .order_by('-quantity_sold', 'product__name')[:8]
    )
    role_counts = list(
        UserProfile.objects.values('role')
        .annotate(total=Count('id'))
        .order_by('role')
    )
    recent_orders = Order.objects.select_related('user', 'promo_code').order_by('-created_at')[:10]

    return JsonResponse(
        {
            'metrics': {
                'total_orders': total_orders,
                'paid_orders': paid_orders,
                'total_sales': _money_string(total_sales),
                'low_stock_products': low_stock_products.count(),
                'low_stock_variants': low_stock_variants.count(),
                'role_counts': role_counts,
            },
            'top_products': list(top_products),
            'low_stock_products': [
                {
                    'id': product.id,
                    'name': product.name,
                    'slug': product.slug,
                    'stock_quantity': product.stock_quantity,
                    'category': product.category.name if product.category else None,
                }
                for product in low_stock_products[:8]
            ],
            'low_stock_variants': [
                {
                    'id': variant.id,
                    'product_id': variant.product_id,
                    'product_name': variant.product.name,
                    'size': variant.size,
                    'color': variant.color,
                    'stock_quantity': variant.stock_quantity,
                }
                for variant in low_stock_variants[:12]
            ],
            'recent_orders': [_serialize_order_detail(order) for order in recent_orders],
        }
    )


@ensure_csrf_cookie
@require_GET
def admin_users(request):
    role_error = _require_roles(request, {UserProfile.ROLE_OWNER, UserProfile.ROLE_ADMIN})
    if role_error:
        return role_error

    users = User.objects.select_related('profile').annotate(order_count=Count('orders')).order_by('username')
    data = []
    for user in users:
        profile = _get_or_create_profile(user)
        data.append(
            {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'role': profile.role,
                'role_label': profile.get_role_display(),
                'order_count': user.order_count,
                'is_staff': user.is_staff,
                'is_superuser': user.is_superuser,
            }
        )

    return JsonResponse({'users': data})


@require_POST
@transaction.atomic
def admin_user_role(request, user_id):
    role_error = _require_roles(request, {UserProfile.ROLE_OWNER})
    if role_error:
        return role_error

    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON payload.'}, status=400)

    role = _normalize_text(payload.get('role')).upper()
    if role not in dict(UserProfile.ROLE_CHOICES):
        return JsonResponse({'error': 'Unsupported role.'}, status=400)

    user = User.objects.filter(id=user_id).first()
    if not user:
        return JsonResponse({'error': 'User not found.'}, status=404)

    profile = _get_or_create_profile(user)
    profile.role = role
    profile.save(update_fields=['role'])

    return JsonResponse({'message': 'Role updated.', 'user': _serialize_user(user)})


@require_POST
@transaction.atomic
def admin_order_status(request, order_id):
    role_error = _require_roles(request, {UserProfile.ROLE_OWNER, UserProfile.ROLE_ADMIN})
    if role_error:
        return role_error

    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON payload.'}, status=400)

    status = _normalize_text(payload.get('status')).upper()
    note = _normalize_text(payload.get('note'))
    if status not in dict(Order.ORDER_STATUS_CHOICES):
        return JsonResponse({'error': 'Unsupported status.'}, status=400)

    order = Order.objects.select_related('promo_code').prefetch_related('items__product', 'items__variant', 'status_events').filter(id=order_id).first()
    if not order:
        return JsonResponse({'error': 'Order not found.'}, status=404)

    if status == Order.STATUS_CANCELLED and not order.is_paid:
        _restore_order_stock(order)
        order.payment_status = Order.PAYMENT_STATUS_FAILED
        order.is_paid = False
    if status == Order.STATUS_DELIVERED and order.payment_method == Order.PAYMENT_COD:
        order.payment_status = Order.PAYMENT_STATUS_PAID
        order.is_paid = True

    order.status = status
    order.save(update_fields=['status', 'payment_status', 'is_paid'])
    OrderStatusEvent.objects.create(order=order, status=status, note=note or f'Status updated to {status}.')

    return JsonResponse({'message': 'Order status updated.', 'order': _serialize_order_detail(order)})
