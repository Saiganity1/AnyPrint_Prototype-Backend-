from django.urls import path

from . import api_views

urlpatterns = [
    path('health/', api_views.health, name='api_health'),
    path('auth/me/', api_views.auth_me, name='api_auth_me'),
    path('auth/register/', api_views.auth_register, name='api_auth_register'),
    path('auth/login/', api_views.auth_login, name='api_auth_login'),
    path('auth/social/', api_views.auth_social_login, name='api_auth_social_login'),
    path('auth/phone/request/', api_views.auth_phone_request, name='api_auth_phone_request'),
    path('auth/phone/verify/', api_views.auth_phone_verify, name='api_auth_phone_verify'),
    path('auth/token/refresh/', api_views.auth_token_refresh, name='api_auth_token_refresh'),
    path('auth/logout/', api_views.auth_logout, name='api_auth_logout'),
    path('categories/', api_views.category_list, name='api_categories'),
    path('products/', api_views.product_list, name='api_products'),
    path('products/<slug:slug>/reviews/', api_views.product_reviews, name='api_product_reviews'),
    path('products/<slug:slug>/reviews/create/', api_views.product_reviews_create, name='api_product_reviews_create'),
    path('products/<int:product_id>/', api_views.product_detail_by_id, name='api_product_detail_by_id'),
    path('products/<slug:slug>/', api_views.product_detail, name='api_product_detail'),
    path('orders/', api_views.create_order, name='api_create_order'),
    path('orders/history/', api_views.order_history, name='api_order_history'),
    path('orders/track/', api_views.order_track, name='api_order_track'),
    path('payments/webhook/', api_views.payment_webhook, name='api_payment_webhook'),
    path('checkout/quote/', api_views.checkout_quote, name='api_checkout_quote'),
    path('wishlist/', api_views.wishlist_list, name='api_wishlist_list'),
    path('wishlist/toggle/', api_views.wishlist_toggle, name='api_wishlist_toggle'),
    path('admin/dashboard/', api_views.admin_dashboard, name='api_admin_dashboard'),
    path('admin/users/', api_views.admin_users, name='api_admin_users'),
    path('admin/users/<int:user_id>/role/', api_views.admin_user_role, name='api_admin_user_role'),
    path('admin/orders/<int:order_id>/status/', api_views.admin_order_status, name='api_admin_order_status'),
]
