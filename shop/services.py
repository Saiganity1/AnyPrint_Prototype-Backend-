from decimal import Decimal

import requests
import stripe
from django.conf import settings


class PaymentGatewayError(Exception):
    pass


def _to_minor_units(amount: Decimal) -> int:
    return int(amount * 100)


def create_stripe_checkout_session(order, cart_items, success_url, cancel_url):
    if not settings.STRIPE_SECRET_KEY:
        raise PaymentGatewayError('Stripe is not configured. Add STRIPE_SECRET_KEY in environment.')

    stripe.api_key = settings.STRIPE_SECRET_KEY
    line_items = []
    for item in cart_items:
        line_items.append(
            {
                'price_data': {
                    'currency': 'php',
                    'product_data': {'name': item['product'].name},
                    'unit_amount': _to_minor_units(item['product'].price),
                },
                'quantity': item['quantity'],
            }
        )

    session = stripe.checkout.Session.create(
        mode='payment',
        line_items=line_items,
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={'order_id': str(order.id)},
    )

    return session.url, session.id


def create_paymongo_checkout_session(order, cart_items, success_url, cancel_url):
    if not settings.PAYMONGO_SECRET_KEY:
        raise PaymentGatewayError('PayMongo is not configured. Add PAYMONGO_SECRET_KEY in environment.')

    line_items = []
    for item in cart_items:
        line_items.append(
            {
                'currency': 'PHP',
                'amount': _to_minor_units(item['product'].price),
                'name': item['product'].name,
                'quantity': item['quantity'],
            }
        )

    payload = {
        'data': {
            'attributes': {
                'send_email_receipt': False,
                'show_description': True,
                'show_line_items': True,
                'description': f'Thread Theory Order #{order.id}',
                'line_items': line_items,
                'payment_method_types': ['gcash', 'card'],
                'success_url': success_url,
                'cancel_url': cancel_url,
            }
        }
    }

    response = requests.post(
        'https://api.paymongo.com/v1/checkout_sessions',
        json=payload,
        auth=(settings.PAYMONGO_SECRET_KEY, ''),
        timeout=30,
    )

    if response.status_code >= 400:
        try:
            details = response.json()
        except ValueError:
            details = response.text
        raise PaymentGatewayError(f'PayMongo checkout creation failed: {details}')

    body = response.json()['data']
    checkout_url = body['attributes']['checkout_url']
    checkout_id = body['id']
    return checkout_url, checkout_id
