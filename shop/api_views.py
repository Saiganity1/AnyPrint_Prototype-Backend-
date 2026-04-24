import csv
import io
import json
import logging
import re
import secrets
from datetime import timedelta
from decimal import Decimal, InvalidOperation

import requests
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.core.cache import cache
from django.conf import settings
from django.core.paginator import EmptyPage, Paginator
from django.db import transaction
from django.db.models import Avg, Count, Q, Sum
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST
from rest_framework_simplejwt.tokens import RefreshToken

from .models import (
    Category,
    Order,
    OrderItem,
    OrderStatusEvent,
    Product,
    ProductReview,
    ProductVariant,
    PromoCode,
    SavedAddress,
    UserProfile,
    WishlistItem,
)
from .notifications import send_order_confirmation_email, send_order_status_email
from .serializers import (
    AdminOrderStatusSerializer,
    AdminUserRoleSerializer,
    AuthLoginSerializer,
    AuthRegisterSerializer,
    CheckoutQuoteSerializer,
    OrderCreateSerializer,
    PaymentWebhookSerializer,
    PhoneAuthRequestSerializer,
    PhoneAuthVerifySerializer,
    ProductReviewCreateSerializer,
    SocialAuthLoginSerializer,
    TrackOrderSerializer,
    WishlistToggleSerializer,
)
from .services import (
    PaymentGatewayError,
    create_paymongo_checkout_session,
    create_paymaya_checkout_session,
    create_stripe_checkout_session,
)

logger = logging.getLogger('shop')

PHONE_OTP_TTL_SECONDS = 300
PHONE_OTP_MAX_ATTEMPTS = 5


def _api_error(message, *, status=400, code='bad_request', details=None):
    payload = {'ok': False, 'error': message, 'code': code}
    if details is not None:
        payload['details'] = details
    return JsonResponse(payload, status=status)


def _api_ok(data=None, *, message='ok', status=200):
    payload = {'ok': True, 'message': message, 'data': data or {}}
    if data:
        payload.update(data)
    return JsonResponse(payload, status=status)


def _serializer_error(serializer):
    return _api_error('Validation error.', status=400, code='validation_error', details=serializer.errors)


def _json_body(request):
    try:
        return json.loads(request.body.decode('utf-8')), None
    except (ValueError, UnicodeDecodeError):
        return None, _api_error('Invalid JSON payload.', status=400, code='invalid_json')


def _client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', 'unknown')


def _rate_limit_exceeded(request, key, limit=20, window_seconds=60):
    cache_key = f'rl:{key}:{_client_ip(request)}'
    current = cache.get(cache_key, 0)
    if current >= limit:
        return True
    cache.set(cache_key, current + 1, timeout=window_seconds)
    return False


def _issue_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {'access': str(refresh.access_token), 'refresh': str(refresh)}


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


def _normalize_phone_number(value):
    cleaned = re.sub(r'[^\d+]', '', _normalize_text(value))
    if cleaned.startswith('00'):
        cleaned = f'+{cleaned[2:]}'
    if cleaned.startswith('0'):
        cleaned = f'+63{cleaned[1:]}'
    return cleaned


def _phone_otp_cache_key(phone_number):
    return f'auth:phone:otp:{phone_number}'


def _phone_otp_attempts_cache_key(phone_number):
    return f'auth:phone:attempts:{phone_number}'


def _generate_phone_otp_code():
    return f'{secrets.randbelow(1000000):06d}'


def _username_seed(value):
    base = re.sub(r'[^a-z0-9_]+', '', _normalize_text(value).lower().replace(' ', '_'))
    return base[:24] or 'user'


def _unique_username(seed):
    candidate = seed[:150] or 'user'
    if not User.objects.filter(username=candidate).exists():
        return candidate

    for _index in range(1, 2000):
        suffix = secrets.token_hex(2)
        candidate = f'{seed[:145]}_{suffix}'[:150]
        if not User.objects.filter(username=candidate).exists():
            return candidate

    return f'user_{secrets.token_hex(6)}'[:150]


def _get_or_create_social_user(*, email='', display_name='', preferred_username=''):
    user = None
    if email:
        user = User.objects.filter(email__iexact=email).first()

    if not user and preferred_username:
        user = User.objects.filter(username=preferred_username).first()

    if user:
        updates = []
        if email and not user.email:
            user.email = email
            updates.append('email')
        if updates:
            user.save(update_fields=updates)
    else:
        seed_value = preferred_username or (email.split('@')[0] if email else display_name)
        username = _unique_username(_username_seed(seed_value))
        user = User(username=username, email=email or '')
        user.set_unusable_password()
        user.save()

    profile = _get_or_create_profile(user)
    if display_name and profile.display_name != display_name:
        profile.display_name = display_name[:120]
        profile.save(update_fields=['display_name'])

    return user


def _verify_google_token(id_token):
    try:
        response = requests.get(
            'https://oauth2.googleapis.com/tokeninfo',
            params={'id_token': id_token},
            timeout=8,
        )
    except requests.RequestException:
        return None, 'Could not verify Google token.'

    if response.status_code != 200:
        return None, 'Invalid Google token.'

    payload = response.json()
    email = _normalize_text(payload.get('email')).lower()
    if not email:
        return None, 'Google account is missing an email address.'

    if str(payload.get('email_verified')).lower() not in {'true', '1'}:
        return None, 'Google email is not verified.'

    return {
        'email': email,
        'display_name': _normalize_text(payload.get('name')),
        'preferred_username': _username_seed(email.split('@')[0]),
    }, ''


def _verify_facebook_token(access_token):
    try:
        response = requests.get(
            'https://graph.facebook.com/me',
            params={'fields': 'id,name,email', 'access_token': access_token},
            timeout=8,
        )
    except requests.RequestException:
        return None, 'Could not verify Facebook token.'

    if response.status_code != 200:
        return None, 'Invalid Facebook token.'

    payload = response.json()
    email = _normalize_text(payload.get('email')).lower()
    if not email:
        return None, 'Facebook account is missing an email address.'

    profile_id = _normalize_text(payload.get('id'))
    preferred_username = _username_seed(email.split('@')[0]) if email else _username_seed(f'fb_{profile_id}')

    return {
        'email': email,
        'display_name': _normalize_text(payload.get('name')),
        'preferred_username': preferred_username,
    }, ''


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
        'phone_number': profile.phone_number or '',
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
    if _rate_limit_exceeded(request, 'auth_register', limit=8, window_seconds=60):
        return _api_error('Too many registration attempts. Please try again later.', status=429, code='rate_limited')

    payload, error_response = _json_body(request)
    if error_response:
        return error_response

    serializer = AuthRegisterSerializer(data=payload)
    if not serializer.is_valid():
        return _serializer_error(serializer)

    username = serializer.validated_data['username']
    email = serializer.validated_data.get('email', '')
    password = serializer.validated_data['password']

    if not username or not password:
        return _api_error('Username and password are required.', status=400, code='validation_error')
    if len(password) < 8:
        return _api_error('Password must be at least 8 characters.', status=400, code='validation_error')
    if User.objects.filter(username=username).exists():
        return _api_error('Username already exists.', status=400, code='validation_error')
    if email and User.objects.filter(email=email).exists():
        return _api_error('Email already exists.', status=400, code='validation_error')

    user = User.objects.create_user(username=username, email=email, password=password)
    _get_or_create_profile(user)
    login(request, user)
    return _api_ok(
        {
            'user': _serialize_user(user),
            'tokens': _issue_tokens_for_user(user),
        },
        message='Registration successful.',
        status=201,
    )


@require_POST
def auth_login(request):
    if _rate_limit_exceeded(request, 'auth_login', limit=12, window_seconds=60):
        return _api_error('Too many login attempts. Please try again later.', status=429, code='rate_limited')

    payload, error_response = _json_body(request)
    if error_response:
        return error_response

    serializer = AuthLoginSerializer(data=payload)
    if not serializer.is_valid():
        return _serializer_error(serializer)

    username = serializer.validated_data['username']
    password = serializer.validated_data['password']

    if not username or not password:
        return _api_error('Username and password are required.', status=400, code='validation_error')

    user = authenticate(request, username=username, password=password)
    if not user:
        return _api_error('Invalid credentials.', status=401, code='auth_failed')

    login(request, user)
    return _api_ok(
        {
            'user': _serialize_user(user),
            'tokens': _issue_tokens_for_user(user),
        },
        message='Login successful.',
    )


@require_POST
def auth_social_login(request):
    if _rate_limit_exceeded(request, 'auth_social_login', limit=20, window_seconds=60):
        return _api_error('Too many social login attempts. Please try again later.', status=429, code='rate_limited')

    payload, error_response = _json_body(request)
    if error_response:
        return error_response

    serializer = SocialAuthLoginSerializer(data=payload)
    if not serializer.is_valid():
        return _serializer_error(serializer)

    provider = serializer.validated_data['provider']
    token = serializer.validated_data['token']

    if provider == 'google':
        identity, verify_error = _verify_google_token(token)
    else:
        identity, verify_error = _verify_facebook_token(token)

    if verify_error:
        return _api_error(verify_error, status=401, code='auth_failed')

    user = _get_or_create_social_user(
        email=identity['email'],
        display_name=identity.get('display_name', ''),
        preferred_username=identity.get('preferred_username', ''),
    )
    login(request, user)
    return _api_ok(
        {
            'user': _serialize_user(user),
            'tokens': _issue_tokens_for_user(user),
            'auth_provider': provider,
        },
        message='Social login successful.',
    )


@require_POST
def auth_phone_request(request):
    if _rate_limit_exceeded(request, 'auth_phone_request', limit=10, window_seconds=60):
        return _api_error('Too many OTP requests. Please try again later.', status=429, code='rate_limited')

    payload, error_response = _json_body(request)
    if error_response:
        return error_response

    serializer = PhoneAuthRequestSerializer(data=payload)
    if not serializer.is_valid():
        return _serializer_error(serializer)

    phone_number = _normalize_phone_number(serializer.validated_data['phone_number'])
    if not re.fullmatch(r'\+[1-9]\d{8,14}', phone_number):
        return _api_error('Enter a valid international phone number.', status=400, code='validation_error')

    otp_code = _generate_phone_otp_code()
    cache.set(_phone_otp_cache_key(phone_number), otp_code, timeout=PHONE_OTP_TTL_SECONDS)
    cache.set(_phone_otp_attempts_cache_key(phone_number), 0, timeout=PHONE_OTP_TTL_SECONDS)
    logger.info('Generated phone OTP for %s', phone_number)

    data = {
        'phone_number': phone_number,
        'expires_in_seconds': PHONE_OTP_TTL_SECONDS,
    }
    if settings.DEBUG:
        data['debug_code'] = otp_code

    return _api_ok(data, message='OTP sent.')


@require_POST
def auth_phone_verify(request):
    if _rate_limit_exceeded(request, 'auth_phone_verify', limit=20, window_seconds=60):
        return _api_error('Too many OTP verification attempts. Please try again later.', status=429, code='rate_limited')

    payload, error_response = _json_body(request)
    if error_response:
        return error_response

    serializer = PhoneAuthVerifySerializer(data=payload)
    if not serializer.is_valid():
        return _serializer_error(serializer)

    phone_number = _normalize_phone_number(serializer.validated_data['phone_number'])
    code = _normalize_text(serializer.validated_data['code'])
    intent = serializer.validated_data.get('intent', 'login')
    cached_code = cache.get(_phone_otp_cache_key(phone_number))
    attempts_key = _phone_otp_attempts_cache_key(phone_number)
    attempts = int(cache.get(attempts_key, 0) or 0)

    if not cached_code:
        return _api_error('OTP expired. Please request a new code.', status=400, code='otp_expired')

    if attempts >= PHONE_OTP_MAX_ATTEMPTS:
        cache.delete(_phone_otp_cache_key(phone_number))
        cache.delete(attempts_key)
        return _api_error('Too many invalid OTP attempts. Request a new code.', status=429, code='rate_limited')

    if code != str(cached_code):
        cache.set(attempts_key, attempts + 1, timeout=PHONE_OTP_TTL_SECONDS)
        return _api_error('Invalid OTP code.', status=401, code='auth_failed')

    cache.delete(_phone_otp_cache_key(phone_number))
    cache.delete(attempts_key)

    existing_profile = UserProfile.objects.select_related('user').filter(phone_number=phone_number).first()
    if existing_profile:
        user = existing_profile.user
        login(request, user)
        return _api_ok(
            {
                'user': _serialize_user(user),
                'tokens': _issue_tokens_for_user(user),
                'auth_provider': 'phone',
                'phone_number': phone_number,
            },
            message='Phone login successful.',
        )

    if intent == 'login':
        return _api_error('No account is linked to this phone number. Please create an account first.', status=404, code='not_found')

    email = _normalize_text(serializer.validated_data.get('email', '')).lower()
    username = _normalize_text(serializer.validated_data.get('username', ''))
    seed = username or f'user_{phone_number[-10:]}'
    preferred_username = _username_seed(seed)
    display_name = f'Phone {phone_number[-4:]}'

    user = _get_or_create_social_user(
        email=email,
        display_name=display_name,
        preferred_username=preferred_username,
    )
    profile = _get_or_create_profile(user)
    if profile.phone_number and profile.phone_number != phone_number:
        return _api_error('This account is already linked to another phone number.', status=400, code='validation_error')

    profile.phone_number = phone_number
    profile.save(update_fields=['phone_number'])

    login(request, user)
    return _api_ok(
        {
            'user': _serialize_user(user),
            'tokens': _issue_tokens_for_user(user),
            'auth_provider': 'phone',
            'phone_number': phone_number,
        },
        message='Phone login successful.',
    )


@require_POST
def auth_logout(request):
    logout(request)
    return _api_ok(message='Logout successful.')


@require_POST
def auth_token_refresh(request):
    payload, error_response = _json_body(request)
    if error_response:
        return error_response

    refresh_token = _normalize_text(payload.get('refresh'))
    if not refresh_token:
        return _api_error('Refresh token is required.', status=400, code='validation_error')

    try:
        refresh = RefreshToken(refresh_token)
        return _api_ok({'tokens': {'access': str(refresh.access_token)}}, message='Token refreshed.')
    except Exception:
        return _api_error('Invalid refresh token.', status=401, code='invalid_token')


@ensure_csrf_cookie
@require_GET
def category_list(request):
    cached = cache.get('api:categories')
    if cached is not None:
        return JsonResponse({'categories': cached})

    categories = Category.objects.all()
    data = [{'id': category.id, 'name': category.name, 'slug': category.slug} for category in categories]
    cache.set('api:categories', data, timeout=300)
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
    if _rate_limit_exceeded(request, 'create_order', limit=20, window_seconds=60):
        return _api_error('Too many order attempts. Please try again shortly.', status=429, code='rate_limited')

    payload, error_response = _json_body(request)
    if error_response:
        return error_response

    idempotency_key = _normalize_text(request.headers.get('Idempotency-Key') or request.META.get('HTTP_IDEMPOTENCY_KEY'))
    if idempotency_key:
        existing_order = Order.objects.select_related('promo_code').prefetch_related('items__product', 'items__variant', 'status_events').filter(idempotency_key=idempotency_key).first()
        if existing_order:
            logger.info('order_idempotency_replay key=%s order_id=%s', idempotency_key, existing_order.id)
            return _api_ok(
                {
                    'order_id': existing_order.id,
                    'tracking_number': existing_order.tracking_number,
                    'payment_status': existing_order.payment_status,
                    'payment_method': existing_order.payment_method,
                    'status': existing_order.status,
                    'redirect_url': existing_order.payment_checkout_url,
                    'idempotency_replayed': True,
                },
                message='Order already processed.',
            )

    serializer = OrderCreateSerializer(data={**payload, 'idempotency_key': idempotency_key})
    if not serializer.is_valid():
        return _serializer_error(serializer)

    quote, error = _build_checkout_quote(serializer.validated_data, request.user)
    if error:
        return _api_error(error, status=400, code='validation_error')

    payment_method = serializer.validated_data['payment_method']

    promo = quote['promo']
    if promo:
        promo.usage_count += 1
        promo.save(update_fields=['usage_count'])

    order = Order.objects.create(
        user=request.user if request.user.is_authenticated else None,
        full_name=serializer.validated_data['full_name'],
        email=serializer.validated_data['email'],
        phone=serializer.validated_data['phone'],
        address=serializer.validated_data['address'],
        payment_method=payment_method,
        notes=serializer.validated_data.get('notes', ''),
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
        idempotency_key=idempotency_key or None,
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
        send_order_confirmation_email(order)
        return _api_ok(
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
            message='Order created.',
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
        elif order.payment_method == Order.PAYMENT_PAYMAYA:
            success_url = request.build_absolute_uri(reverse('shop:paymaya_success', args=[order.id]))
            cancel_url = request.build_absolute_uri(reverse('shop:payment_cancel', args=[order.id]))
            checkout_url, reference = create_paymaya_checkout_session(order, gateway_items, success_url, cancel_url)
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
    send_order_confirmation_email(order)

    return _api_ok(
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
        message='Order created.',
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
    payload, error_response = _json_body(request)
    if error_response:
        return error_response

    serializer = CheckoutQuoteSerializer(data=payload)
    if not serializer.is_valid():
        return _serializer_error(serializer)

    quote, error = _build_checkout_quote(serializer.validated_data, request.user)
    if error:
        return _api_error(error, status=400, code='validation_error')

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

    serializer = ProductReviewCreateSerializer(data=payload)
    if not serializer.is_valid():
        return _serializer_error(serializer)

    review, _created = ProductReview.objects.update_or_create(
        product=product,
        user=request.user,
        defaults={
            'rating': serializer.validated_data['rating'],
            'title': serializer.validated_data.get('title', ''),
            'comment': serializer.validated_data.get('comment', ''),
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

    serializer = WishlistToggleSerializer(data=payload)
    if not serializer.is_valid():
        return _serializer_error(serializer)

    product_id = serializer.validated_data['product_id']
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
    if _rate_limit_exceeded(request, 'order_track', limit=40, window_seconds=60):
        return _api_error('Too many tracking requests. Please try again shortly.', status=429, code='rate_limited')

    serializer = TrackOrderSerializer(data={
        'tracking_number': request.GET.get('tracking_number', ''),
        'order_id': request.GET.get('order_id') or None,
        'email': request.GET.get('email', ''),
    })
    if not serializer.is_valid():
        return _serializer_error(serializer)

    tracking_number = serializer.validated_data.get('tracking_number', '')
    order_id = serializer.validated_data.get('order_id')
    email = serializer.validated_data.get('email', '')

    order = None
    if tracking_number:
        order = Order.objects.select_related('user', 'promo_code').prefetch_related('items__product', 'items__variant', 'status_events').filter(tracking_number=tracking_number).first()
    elif order_id:
        order = Order.objects.select_related('user', 'promo_code').prefetch_related('items__product', 'items__variant', 'status_events').filter(id=order_id).first()

    if not order:
        return _api_error('Order not found.', status=404, code='not_found')

    if request.user.is_authenticated:
        role = _get_user_role(request.user)
        if role not in {UserProfile.ROLE_OWNER, UserProfile.ROLE_ADMIN} and order.user_id and order.user_id != request.user.id:
            return _api_error('Permission denied.', status=403, code='forbidden')
    elif email and order.email.lower() != email.lower():
        return _api_error('Order email does not match.', status=403, code='forbidden')

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

    serializer = AdminUserRoleSerializer(data=payload)
    if not serializer.is_valid():
        return _serializer_error(serializer)

    role = serializer.validated_data['role']

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

    serializer = AdminOrderStatusSerializer(data=payload)
    if not serializer.is_valid():
        return _serializer_error(serializer)

    status = serializer.validated_data['status']
    note = serializer.validated_data.get('note', '')

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
    send_order_status_email(order, note=note)

    return JsonResponse({'message': 'Order status updated.', 'order': _serialize_order_detail(order)})


@require_POST
@transaction.atomic
def payment_webhook(request):
    payload, error_response = _json_body(request)
    if error_response:
        return error_response

    serializer = PaymentWebhookSerializer(data=payload)
    if not serializer.is_valid():
        return _serializer_error(serializer)

    provider = serializer.validated_data['provider']
    event_type = serializer.validated_data['event_type']
    order_id = serializer.validated_data.get('order_id')
    payment_reference = serializer.validated_data.get('payment_reference', '')
    note = serializer.validated_data.get('note', '')

    order = None
    if order_id:
        order = Order.objects.select_related('promo_code').prefetch_related('items__product', 'items__variant', 'status_events').filter(id=order_id).first()
    if not order and payment_reference:
        order = Order.objects.select_related('promo_code').prefetch_related('items__product', 'items__variant', 'status_events').filter(payment_reference=payment_reference).first()

    if not order:
        return _api_error('Order not found.', status=404, code='not_found')

    normalized_event = event_type.lower()
    if normalized_event in {'payment.paid', 'checkout.success', 'payment_succeeded'}:
        order.payment_status = Order.PAYMENT_STATUS_PAID
        order.is_paid = True
        if order.status == Order.STATUS_PENDING:
            order.status = Order.STATUS_CONFIRMED
        order.save(update_fields=['payment_status', 'is_paid', 'status'])
        OrderStatusEvent.objects.create(order=order, status=order.status, note=note or f'{provider} webhook confirmed payment.')
        send_order_status_email(order, note=note or f'{provider} webhook confirmed payment.')
        return _api_ok({'order': _serialize_order_detail(order)}, message='Webhook processed.')

    if normalized_event in {'payment.failed', 'checkout.failed', 'payment_failed'}:
        order.payment_status = Order.PAYMENT_STATUS_FAILED
        order.status = Order.STATUS_CANCELLED
        order.save(update_fields=['payment_status', 'status'])
        OrderStatusEvent.objects.create(order=order, status=order.status, note=note or f'{provider} webhook reported failure.')
        send_order_status_email(order, note=note or f'{provider} webhook reported failure.')
        return _api_ok({'order': _serialize_order_detail(order)}, message='Webhook processed.')

    return _api_ok({'order': _serialize_order_detail(order)}, message='Webhook ignored.')


@require_GET
def admin_orders(request):
    """Get list of all orders for admin dashboard"""
    role_error = _require_roles(request, {UserProfile.ROLE_OWNER, UserProfile.ROLE_ADMIN})
    if role_error:
        return role_error
    
    page = request.GET.get('page', 1)
    page_size = request.GET.get('page_size', 50)
    
    orders_qs = Order.objects.select_related('user', 'promo_code').order_by('-created_at')
    
    paginator = Paginator(orders_qs, page_size)
    try:
        orders_page = paginator.page(page)
    except:
        orders_page = paginator.page(1)
    
    orders = []
    for order in orders_page:
        orders.append({
            'id': order.id,
            'tracking_number': order.tracking_number,
            'full_name': order.full_name,
            'email': order.email,
            'phone': order.phone,
            'total_amount': str(order.total_amount),
            'status': order.status,
            'payment_status': order.payment_status,
            'payment_method': order.payment_method,
            'created_at': order.created_at.isoformat(),
        })
    
    return JsonResponse({
        'orders': orders,
        'total': paginator.count,
        'pages': paginator.num_pages,
        'current_page': orders_page.number,
    })


@require_GET
def admin_products(request):
    """Get list of products for admin management"""
    role_error = _require_roles(request, {UserProfile.ROLE_OWNER, UserProfile.ROLE_ADMIN})
    if role_error:
        return role_error
    
    page = request.GET.get('page', 1)
    page_size = request.GET.get('page_size', 100)
    
    products_qs = Product.objects.select_related('category').order_by('-created_at')
    
    paginator = Paginator(products_qs, page_size)
    try:
        products_page = paginator.page(page)
    except:
        products_page = paginator.page(1)
    
    products = []
    for product in products_page:
        products.append({
            'id': product.id,
            'name': product.name,
            'slug': product.slug,
            'category': product.category.name if product.category else None,
            'price': str(product.price),
            'stock_quantity': product.stock_quantity,
            'is_featured': product.is_featured,
            'is_active': product.is_active,
        })
    
    return JsonResponse({
        'products': products,
        'total': paginator.count,
        'pages': paginator.num_pages,
        'current_page': products_page.number,
    })


@require_POST
@transaction.atomic
def admin_product_delete(request, product_id):
    """Delete a product"""
    role_error = _require_roles(request, {UserProfile.ROLE_OWNER, UserProfile.ROLE_ADMIN})
    if role_error:
        return role_error
    
    product = Product.objects.filter(id=product_id).first()
    if not product:
        return JsonResponse({'error': 'Product not found.'}, status=404)
    
    product_name = product.name
    product.delete()
    
    return JsonResponse({'message': f'Product \"{product_name}\" deleted successfully.'})


@require_POST
@transaction.atomic
def admin_products_bulk_upload(request):
    """Bulk upload products via CSV"""
    role_error = _require_roles(request, {UserProfile.ROLE_OWNER})
    if role_error:
        return role_error
    
    if 'file' not in request.FILES:
        return JsonResponse({'error': 'No file provided.'}, status=400)
    
    csv_file = request.FILES['file']
    if not csv_file.name.endswith('.csv'):
        return JsonResponse({'error': 'Please upload a CSV file.'}, status=400)
    
    try:
        file_content = csv_file.read().decode('utf-8')
        csv_reader = csv.DictReader(io.StringIO(file_content))
        
        created = 0
        updated = 0
        errors = []
        
        for row_num, row in enumerate(csv_reader, start=2):
            try:
                category_name = row.get('category', '').strip()
                category = None
                if category_name:
                    category, _ = Category.objects.get_or_create(name=category_name)
                
                product_data = {
                    'description': row.get('description', ''),
                    'price': Decimal(row.get('price', '0')),
                    'stock_quantity': int(row.get('stock_quantity', '0')),
                    'category': category,
                    'is_featured': row.get('is_featured', 'false').lower() == 'true',
                }
                
                product, was_created = Product.objects.update_or_create(
                    name=row.get('name', '').strip(),
                    defaults=product_data
                )
                
                if was_created:
                    created += 1
                else:
                    updated += 1
            except Exception as e:
                errors.append(f'Row {row_num}: {str(e)}')
        
        return JsonResponse({
            'message': f'Imported {created} new products, updated {updated} existing products.',
            'created': created,
            'updated': updated,
            'errors': errors[:10],
        })
    
    except Exception as e:
        return JsonResponse({'error': f'Failed to process CSV: {str(e)}'}, status=400)


@require_GET
def user_addresses(request):
    """Get user's saved addresses"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required.'}, status=401)
    
    addresses = SavedAddress.objects.filter(user=request.user).order_by('-is_default', '-updated_at')
    
    return JsonResponse({
        'addresses': [
            {
                'id': addr.id,
                'full_name': addr.full_name,
                'phone': addr.phone,
                'address': addr.address,
                'is_default': addr.is_default,
                'created_at': addr.created_at.isoformat(),
            }
            for addr in addresses
        ]
    })


@require_POST
@transaction.atomic
def user_address_create(request):
    """Create a new saved address"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required.'}, status=401)
    
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON payload.'}, status=400)
    
    full_name = payload.get('full_name', '').strip()
    phone = payload.get('phone', '').strip()
    address = payload.get('address', '').strip()
    is_default = payload.get('is_default', False)
    
    if not full_name or not phone or not address:
        return JsonResponse({'error': 'Missing required fields: full_name, phone, address.'}, status=400)
    
    if is_default:
        SavedAddress.objects.filter(user=request.user, is_default=True).update(is_default=False)
    
    addr = SavedAddress.objects.create(
        user=request.user,
        full_name=full_name,
        phone=phone,
        address=address,
        is_default=is_default
    )
    
    return JsonResponse({
        'message': 'Address created successfully.',
        'address': {
            'id': addr.id,
            'full_name': addr.full_name,
            'phone': addr.phone,
            'address': addr.address,
            'is_default': addr.is_default,
        }
    })


@require_POST
@transaction.atomic
def user_address_detail(request, address_id):
    """Update a saved address"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required.'}, status=401)
    
    addr = SavedAddress.objects.filter(id=address_id, user=request.user).first()
    if not addr:
        return JsonResponse({'error': 'Address not found.'}, status=404)
    
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON payload.'}, status=400)
    
    if 'full_name' in payload:
        addr.full_name = payload['full_name'].strip()
    if 'phone' in payload:
        addr.phone = payload['phone'].strip()
    if 'address' in payload:
        addr.address = payload['address'].strip()
    if 'is_default' in payload:
        if payload['is_default']:
            SavedAddress.objects.filter(user=request.user, is_default=True).update(is_default=False)
        addr.is_default = payload['is_default']
    
    addr.save()
    
    return JsonResponse({
        'message': 'Address updated successfully.',
        'address': {
            'id': addr.id,
            'full_name': addr.full_name,
            'phone': addr.phone,
            'address': addr.address,
            'is_default': addr.is_default,
        }
    })


@require_POST
@transaction.atomic
def user_address_delete(request, address_id):
    """Delete a saved address"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required.'}, status=401)
    
    addr = SavedAddress.objects.filter(id=address_id, user=request.user).first()
    if not addr:
        return JsonResponse({'error': 'Address not found.'}, status=404)
    
    addr.delete()
    
    return JsonResponse({'message': 'Address deleted successfully.'})


@require_GET
def admin_analytics(request):
    """Get sales analytics and reports"""
    role_error = _require_roles(request, {UserProfile.ROLE_OWNER, UserProfile.ROLE_ADMIN})
    if role_error:
        return role_error
    
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    
    orders_qs = Order.objects.select_related('user', 'promo_code').prefetch_related('items__product')
    
    if date_from:
        try:
            date_from = timezone.datetime.fromisoformat(date_from).date()
            orders_qs = orders_qs.filter(created_at__date__gte=date_from)
        except:
            pass
    
    if date_to:
        try:
            date_to = timezone.datetime.fromisoformat(date_to).date()
            orders_qs = orders_qs.filter(created_at__date__lte=date_to)
        except:
            pass
    
    # Sales metrics
    total_orders = orders_qs.count()
    paid_orders = orders_qs.filter(is_paid=True).count()
    total_revenue = orders_qs.filter(is_paid=True).aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    average_order_value = total_revenue / paid_orders if paid_orders > 0 else Decimal('0.00')
    
    # Payment method breakdown
    payment_breakdown = list(
        orders_qs.values('payment_method')
        .annotate(count=Count('id'), total=Sum('total_amount'))
        .order_by('-count')
    )
    
    # Top products
    top_products = list(
        OrderItem.objects.filter(order__in=orders_qs)
        .values('product_id', 'product__name', 'product__slug')
        .annotate(quantity_sold=Sum('quantity'), revenue=Sum('subtotal'))
        .order_by('-quantity_sold')[:10]
    )
    
    # Order status breakdown
    status_breakdown = list(
        orders_qs.values('status')
        .annotate(count=Count('id'))
        .order_by('status')
    )
    
    # Daily sales trend (last 30 days)
    from django.db.models.functions import TruncDate
    daily_sales = list(
        orders_qs.filter(is_paid=True)
        .annotate(date=TruncDate('created_at'))
        .values('date')
        .annotate(revenue=Sum('total_amount'), order_count=Count('id'))
        .order_by('date')
    )
    
    return JsonResponse({
        'metrics': {
            'total_orders': total_orders,
            'paid_orders': paid_orders,
            'total_revenue': str(total_revenue),
            'average_order_value': str(average_order_value),
            'pending_orders': orders_qs.filter(status=Order.STATUS_PENDING).count(),
            'completed_orders': orders_qs.filter(status=Order.STATUS_DELIVERED).count(),
        },
        'payment_breakdown': payment_breakdown,
        'status_breakdown': status_breakdown,
        'top_products': top_products,
        'daily_sales': [
            {
                'date': str(item['date']),
                'revenue': str(item['revenue']),
                'order_count': item['order_count'],
            }
            for item in daily_sales
        ],
    })
