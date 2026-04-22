from django.conf import settings
from django.core.mail import send_mail


def _from_email():
    return getattr(settings, 'DEFAULT_FROM_EMAIL', '') or getattr(settings, 'EMAIL_HOST_USER', '') or 'no-reply@anyprint.local'


def send_order_confirmation_email(order):
    subject = f'AnyPrint order #{order.id} confirmed'
    message = (
        f'Hi {order.full_name},\n\n'
        f'Your AnyPrint order #{order.id} has been created.\n'
        f'Tracking number: {order.tracking_number}\n'
        f'Total: {order.total_amount}\n'
        f'Payment method: {order.payment_method}\n\n'
        'We will send another update when the order status changes.'
    )
    send_mail(subject, message, _from_email(), [order.email], fail_silently=True)


def send_order_status_email(order, *, note=''):
    subject = f'AnyPrint order #{order.id} status update'
    message = (
        f'Hi {order.full_name},\n\n'
        f'Your order #{order.id} status changed to {order.status}.\n'
        f'Tracking number: {order.tracking_number}\n'
        f'Payment status: {order.payment_status}\n'
    )
    if note:
        message += f'\nNote: {note}\n'
    send_mail(subject, message, _from_email(), [order.email], fail_silently=True)
