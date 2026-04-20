from django.urls import path

from . import api_views

urlpatterns = [
    path('health/', api_views.health, name='api_health'),
    path('auth/me/', api_views.auth_me, name='api_auth_me'),
    path('auth/register/', api_views.auth_register, name='api_auth_register'),
    path('auth/login/', api_views.auth_login, name='api_auth_login'),
    path('auth/logout/', api_views.auth_logout, name='api_auth_logout'),
    path('categories/', api_views.category_list, name='api_categories'),
    path('products/', api_views.product_list, name='api_products'),
    path('orders/', api_views.create_order, name='api_create_order'),
]
