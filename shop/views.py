from decimal import Decimal

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import slugify

from .forms import CheckoutForm
from .models import Category, Order, OrderItem, Product
from .services import (
    PaymentGatewayError,
    create_paymongo_checkout_session,
    create_stripe_checkout_session,
)


def _bootstrap_products_if_empty():
    if Product.objects.exists():
        return

    category_names = ['Essentials', 'Graphic', 'Oversized']
    category_map = {}
    for category_name in category_names:
        category = Category.objects.create(name=category_name, slug=slugify(category_name))
        category_map[category_name] = category

    starter_products = [
        ('Classic White Tee', 'A premium cotton shirt for daily comfort.', Decimal('499.00'), True, 'Essentials', 30),
        ('Ocean Blue Oversize', 'Relaxed fit with breathable fabric and streetwear vibe.', Decimal('699.00'), True, 'Oversized', 20),
        ('Minimal Black Tee', 'Soft heavyweight shirt with clean modern styling.', Decimal('649.00'), False, 'Essentials', 25),
        ('Sunset Graphic Shirt', 'Limited print inspired by tropical city sunsets.', Decimal('799.00'), True, 'Graphic', 12),
        ('Olive Utility Tee', 'Durable and versatile with all-day comfort.', Decimal('599.00'), False, 'Oversized', 18),
        ('Sand Beige Essential', 'Neutral tone shirt that pairs with anything.', Decimal('549.00'), False, 'Essentials', 22),
    ]

    for name, description, price, is_featured, category_name, stock_qty in starter_products:
        Product.objects.create(
            name=name,
            slug=slugify(name),
            category=category_map[category_name],
            description=description,
            price=price,
            stock_quantity=stock_qty,
            is_featured=is_featured,
        )


def _get_cart(session):
    return session.setdefault('cart', {})


def _build_cart_items(cart):
    items = []
    total = Decimal('0.00')

    for product_id, qty in cart.items():
        product = Product.objects.filter(pk=int(product_id), is_active=True).first()
        if not product:
            continue

        quantity = int(qty)
        subtotal = product.price * quantity
        items.append(
            {
                'product': product,
                'quantity': quantity,
                'subtotal': subtotal,
                'is_stock_enough': quantity <= product.stock_quantity,
            }
        )
        total += subtotal

    return items, total


def _restore_order_stock(order):
    for item in order.items.select_related('product'):
        product = item.product
        product.stock_quantity += item.quantity
        product.save(update_fields=['stock_quantity'])


def _reserve_stock(cart_items):
    for item in cart_items:
        product = item['product']
        if item['quantity'] > product.stock_quantity:
            return f"Insufficient stock for {product.name}. Available: {product.stock_quantity}"

    for item in cart_items:
        product = item['product']
        product.stock_quantity -= item['quantity']
        product.save(update_fields=['stock_quantity'])

    return ''


def product_list(request):
    _bootstrap_products_if_empty()
    category_slug = request.GET.get('category', '')
    products = Product.objects.filter(is_active=True)
    categories = Category.objects.all()
    selected_category = None

    if category_slug:
        selected_category = categories.filter(slug=category_slug).first()
        if selected_category:
            products = products.filter(category=selected_category)

    return render(
        request,
        'shop/product_list.html',
        {
            'products': products,
            'categories': categories,
            'selected_category': selected_category,
        },
    )


def add_to_cart(request, product_id):
    product = get_object_or_404(Product, pk=product_id, is_active=True)
    cart = _get_cart(request.session)
    key = str(product_id)
    new_qty = cart.get(key, 0) + 1

    if new_qty > product.stock_quantity:
        messages.error(request, f'Only {product.stock_quantity} in stock for {product.name}.')
        return redirect('shop:product_list')

    cart[key] = new_qty
    request.session.modified = True
    messages.success(request, f'{product.name} added to cart.')
    return redirect('shop:product_list')


def cart_detail(request):
    cart = _get_cart(request.session)
    cart_items, total = _build_cart_items(cart)
    has_stock_issue = any(not item['is_stock_enough'] for item in cart_items)
    return render(
        request,
        'shop/cart_detail.html',
        {'cart_items': cart_items, 'total': total, 'has_stock_issue': has_stock_issue},
    )


def update_cart_item(request, product_id):
    if request.method == 'POST':
        cart = _get_cart(request.session)
        key = str(product_id)
        product = get_object_or_404(Product, pk=product_id, is_active=True)
        quantity = max(int(request.POST.get('quantity', 1)), 1)

        if quantity > product.stock_quantity:
            messages.error(request, f'Only {product.stock_quantity} available for {product.name}.')
            return redirect('shop:cart_detail')

        cart[key] = quantity
        request.session.modified = True
        messages.info(request, 'Cart updated.')

    return redirect('shop:cart_detail')


def remove_from_cart(request, product_id):
    cart = _get_cart(request.session)
    key = str(product_id)
    if key in cart:
        del cart[key]
        request.session.modified = True
        messages.warning(request, 'Item removed from cart.')
    return redirect('shop:cart_detail')


@transaction.atomic
def checkout(request):
    cart = _get_cart(request.session)
    cart_items, total = _build_cart_items(cart)

    if not cart_items:
        messages.error(request, 'Your cart is empty.')
        return redirect('shop:product_list')

    for item in cart_items:
        if item['quantity'] > item['product'].stock_quantity:
            messages.error(request, f"{item['product'].name} no longer has enough stock.")
            return redirect('shop:cart_detail')

    if request.method == 'POST':
        form = CheckoutForm(request.POST)
        if form.is_valid():
            order = form.save(commit=False)
            order.total_amount = total
            order.payment_status = Order.STATUS_PENDING
            order.is_paid = False
            order.save()

            for item in cart_items:
                OrderItem.objects.create(
                    order=order,
                    product=item['product'],
                    quantity=item['quantity'],
                    unit_price=item['product'].price,
                )

            stock_error = _reserve_stock(cart_items)
            if stock_error:
                messages.error(request, stock_error)
                return redirect('shop:cart_detail')

            if order.payment_method == Order.PAYMENT_COD:
                request.session['cart'] = {}
                request.session.modified = True
                return redirect('shop:order_success', order_id=order.id)

            if order.payment_method == Order.PAYMENT_BANK:
                request.session['cart'] = {}
                request.session.modified = True
                messages.info(request, 'Bank transfer selected. Please follow payment instructions after order confirmation.')
                return redirect('shop:order_success', order_id=order.id)

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
                    messages.error(request, 'Unsupported payment method.')
                    _restore_order_stock(order)
                    order.payment_status = Order.STATUS_FAILED
                    order.save(update_fields=['payment_status'])
                    return redirect('shop:checkout')
            except PaymentGatewayError as error:
                _restore_order_stock(order)
                order.payment_status = Order.STATUS_FAILED
                order.save(update_fields=['payment_status'])
                messages.error(request, str(error))
                return redirect('shop:checkout')

            order.payment_reference = reference
            order.payment_checkout_url = checkout_url
            order.save(update_fields=['payment_reference', 'payment_checkout_url'])
            request.session['cart'] = {}
            request.session.modified = True
            return redirect(checkout_url)
    else:
        form = CheckoutForm()

    return render(
        request,
        'shop/checkout.html',
        {
            'form': form,
            'cart_items': cart_items,
            'total': total,
        },
    )


def order_success(request, order_id):
    order = get_object_or_404(Order, pk=order_id)
    return render(request, 'shop/order_success.html', {'order': order})


@transaction.atomic
def stripe_success(request, order_id):
    order = get_object_or_404(Order, pk=order_id)
    order.payment_status = Order.STATUS_PAID
    order.is_paid = True
    order.save(update_fields=['payment_status', 'is_paid'])
    return redirect('shop:order_success', order_id=order.id)


@transaction.atomic
def paymongo_success(request, order_id):
    order = get_object_or_404(Order, pk=order_id)
    order.payment_status = Order.STATUS_PAID
    order.is_paid = True
    order.save(update_fields=['payment_status', 'is_paid'])
    return redirect('shop:order_success', order_id=order.id)


@transaction.atomic
def payment_cancel(request, order_id):
    order = get_object_or_404(Order, pk=order_id)
    if not order.is_paid and order.payment_status != Order.STATUS_FAILED:
        _restore_order_stock(order)
        order.payment_status = Order.STATUS_FAILED
        order.save(update_fields=['payment_status'])

    messages.warning(request, 'Payment was cancelled. Your reserved stock was released.')
    return redirect('shop:cart_detail')
