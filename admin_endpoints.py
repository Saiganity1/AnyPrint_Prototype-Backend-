# New admin API endpoints to be appended to shop/api_views.py

import csv
import io
from django.views.decorators.http import require_POST, require_GET

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
    
    return JsonResponse({'message': f'Product "{product_name}" deleted successfully.'})


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
            'errors': errors[:10],  # Limit to first 10 errors
        })
    
    except Exception as e:
        return JsonResponse({'error': f'Failed to process CSV: {str(e)}'}, status=400)


@require_GET
def user_addresses(request):
    """Get user's saved addresses"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required.'}, status=401)
    
    # For now, return empty list as SavedAddress model doesn't exist yet
    # This will be implemented after creating the model
    return JsonResponse({'addresses': []})


@require_POST
@transaction.atomic
def user_address_create(request):
    """Add a new saved address"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required.'}, status=401)
    
    # Placeholder for future implementation with SavedAddress model
    return JsonResponse({'error': 'Not yet implemented.'}, status=501)
