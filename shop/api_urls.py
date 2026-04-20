from django.urls import path

from . import api_views

urlpatterns = [
    path('health/', api_views.health, name='api_health'),
    path('categories/', api_views.category_list, name='api_categories'),
    path('products/', api_views.product_list, name='api_products'),
    path('orders/', api_views.create_order, name='api_create_order'),
]
