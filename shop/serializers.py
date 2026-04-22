from rest_framework import serializers

from .models import Order, ProductReview, UserProfile


class AuthRegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150, trim_whitespace=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    password = serializers.CharField(min_length=8, write_only=True)


class AuthLoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150, trim_whitespace=True)
    password = serializers.CharField(write_only=True)


class SocialAuthLoginSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=['google', 'facebook'])
    token = serializers.CharField(trim_whitespace=True)


class PhoneAuthRequestSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=32, trim_whitespace=True)


class PhoneAuthVerifySerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=32, trim_whitespace=True)
    code = serializers.CharField(max_length=6, trim_whitespace=True)
    intent = serializers.ChoiceField(choices=['login', 'register'], required=False, default='login')
    username = serializers.CharField(max_length=150, trim_whitespace=True, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)


class CheckoutItemSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(required=False, allow_null=True)
    variant_id = serializers.IntegerField(required=False, allow_null=True)
    size = serializers.CharField(required=False, allow_blank=True, default='')
    color = serializers.CharField(required=False, allow_blank=True, default='')
    quantity = serializers.IntegerField(min_value=1)


class CheckoutQuoteSerializer(serializers.Serializer):
    items = CheckoutItemSerializer(many=True)
    address = serializers.CharField(allow_blank=True, required=False, default='')
    promo_code = serializers.CharField(allow_blank=True, required=False, default='')


class OrderCreateSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=120)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=30)
    address = serializers.CharField()
    payment_method = serializers.ChoiceField(choices=Order.PAYMENT_METHOD_CHOICES)
    items = CheckoutItemSerializer(many=True)
    notes = serializers.CharField(allow_blank=True, required=False, default='')
    promo_code = serializers.CharField(allow_blank=True, required=False, default='')
    idempotency_key = serializers.CharField(allow_blank=True, required=False, default='')


class TrackOrderSerializer(serializers.Serializer):
    tracking_number = serializers.CharField(allow_blank=True, required=False, default='')
    order_id = serializers.IntegerField(required=False, allow_null=True)
    email = serializers.EmailField(required=False, allow_blank=True, default='')


class AdminOrderStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Order.ORDER_STATUS_CHOICES)
    note = serializers.CharField(allow_blank=True, required=False, default='')


class AdminUserRoleSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=UserProfile.ROLE_CHOICES)


class WishlistToggleSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()


class ProductReviewCreateSerializer(serializers.Serializer):
    rating = serializers.IntegerField(min_value=1, max_value=5)
    title = serializers.CharField(required=False, allow_blank=True, default='')
    comment = serializers.CharField(required=False, allow_blank=True, default='')


class PaymentWebhookSerializer(serializers.Serializer):
    provider = serializers.CharField(max_length=32)
    event_type = serializers.CharField(max_length=64)
    order_id = serializers.IntegerField(required=False, allow_null=True)
    payment_reference = serializers.CharField(required=False, allow_blank=True, default='')
    status = serializers.CharField(required=False, allow_blank=True, default='')
    note = serializers.CharField(required=False, allow_blank=True, default='')
