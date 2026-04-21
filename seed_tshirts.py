import os
from decimal import Decimal

import django


def main() -> None:
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tshirt_store.settings')
    django.setup()

    from django.utils.text import slugify  # noqa: PLC0415

    from django.contrib.auth.models import User  # noqa: PLC0415

    from shop.models import Category, Product, ProductVariant, PromoCode, UserProfile  # noqa: PLC0415

    categories = [
        {'name': 'Unisex - Light Weight', 'slug': 'unisex-light-weight'},
        {'name': 'Unisex - Heavy Weight', 'slug': 'unisex-heavy-weight'},
        {'name': 'Graphic Tees', 'slug': 'graphic-tees'},
        {'name': 'Kids Tees', 'slug': 'kids-tees'},
    ]

    category_map: dict[str, Category] = {}
    created_categories = 0
    updated_categories = 0

    for item in categories:
        category, created = Category.objects.update_or_create(
            slug=item['slug'],
            defaults={'name': item['name']},
        )
        category_map[category.slug] = category
        if created:
            created_categories += 1
        else:
            updated_categories += 1

    products = [
        {
            'name': 'Unisex Light Weight Tee',
            'category_slug': 'unisex-light-weight',
            'price': Decimal('225.00'),
            'stock_quantity': 40,
            'is_featured': True,
            'print_style': 'Classic',
            'colors': ['Black', 'White'],
            'description': 'Soft, breathable tee for daily wear. Clean silhouette and easy layering.',
        },
        {
            'name': 'Unisex Heavy Weight Tee',
            'category_slug': 'unisex-heavy-weight',
            'price': Decimal('300.00'),
            'stock_quantity': 30,
            'is_featured': True,
            'print_style': 'Minimal',
            'colors': ['Black', 'Sand'],
            'description': 'Thicker fabric with a structured drape. Built for a premium streetwear look.',
        },
        {
            'name': 'Oversized Street Tee',
            'category_slug': 'unisex-heavy-weight',
            'price': Decimal('320.00'),
            'stock_quantity': 25,
            'is_featured': False,
            'print_style': 'Street',
            'colors': ['Black', 'Olive', 'Sand'],
            'description': 'Relaxed oversized cut with roomy sleeves. Designed for a modern street fit.',
        },
        {
            'name': 'Graphic Tee - Minimal Mark',
            'category_slug': 'graphic-tees',
            'price': Decimal('280.00'),
            'stock_quantity': 20,
            'is_featured': True,
            'print_style': 'Graphic',
            'colors': ['Black', 'Cream', 'Navy'],
            'description': 'Minimal front mark graphic on a clean base. Limited-drop style for a clean look.',
        },
        {
            'name': 'Graphic Tee - Back Print',
            'category_slug': 'graphic-tees',
            'price': Decimal('290.00'),
            'stock_quantity': 18,
            'is_featured': False,
            'print_style': 'Graphic',
            'colors': ['Black', 'Cream'],
            'description': 'Bold back print with small front detail. Made for statement outfits.',
        },
        {
            'name': 'Kids Comfort Tee',
            'category_slug': 'kids-tees',
            'price': Decimal('250.00'),
            'stock_quantity': 35,
            'is_featured': False,
            'print_style': 'Kids',
            'colors': ['White', 'Sky', 'Mint'],
            'description': 'Comfort-first tee for kids. Soft feel with easy movement for all-day wear.',
        },
    ]

    created_products = 0
    updated_products = 0

    for item in products:
        slug = slugify(item['name'])
        category = category_map[item['category_slug']]
        _, created = Product.objects.update_or_create(
            slug=slug,
            defaults={
                'name': item['name'],
                'category': category,
                'description': item['description'],
                'price': item['price'],
                'stock_quantity': item['stock_quantity'],
                'is_active': True,
                'is_featured': item['is_featured'],
                'print_style': item['print_style'],
            },
        )
        if created:
            created_products += 1
        else:
            updated_products += 1

        product = Product.objects.get(slug=slug)
        ProductVariant.objects.filter(product=product).delete()
        sizes = [ProductVariant.SIZE_S, ProductVariant.SIZE_M, ProductVariant.SIZE_L, ProductVariant.SIZE_XL]
        combinations = [(size, color) for size in sizes for color in item['colors']]
        base_stock = item['stock_quantity'] // len(combinations)
        remainder = item['stock_quantity'] % len(combinations)

        for index, (size, color) in enumerate(combinations):
            variant_stock = base_stock + (1 if index < remainder else 0)
            ProductVariant.objects.create(
                product=product,
                size=size,
                color=color,
                stock_quantity=variant_stock,
                sku=slugify(f'{product.slug}-{size}-{color}'),
            )

    demo_accounts = [
        ('owner', 'owner1234', 'owner@anyprint.local', True, True, UserProfile.ROLE_OWNER),
        ('admin', 'admin1234', 'admin@anyprint.local', False, True, UserProfile.ROLE_ADMIN),
        ('customer', 'customer1234', 'customer@anyprint.local', False, False, UserProfile.ROLE_USER),
    ]

    for username, password, email, is_superuser, is_staff, role in demo_accounts:
        user, created = User.objects.get_or_create(username=username, defaults={'email': email})
        if created:
            user.set_password(password)
        else:
            user.email = email
        user.is_superuser = is_superuser
        user.is_staff = is_staff
        user.save()
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.role = role
        profile.save(update_fields=['role'])

    promo_codes = [
        {'code': 'WELCOME10', 'discount_type': PromoCode.DISCOUNT_PERCENT, 'value': Decimal('10.00'), 'minimum_subtotal': Decimal('500.00'), 'first_order_only': True},
        {'code': 'BUNDLE15', 'discount_type': PromoCode.DISCOUNT_PERCENT, 'value': Decimal('15.00'), 'minimum_subtotal': Decimal('1000.00'), 'first_order_only': False},
        {'code': 'SHIPFREE', 'discount_type': PromoCode.DISCOUNT_FIXED, 'value': Decimal('0.00'), 'minimum_subtotal': Decimal('2000.00'), 'first_order_only': False},
    ]

    for item in promo_codes:
        PromoCode.objects.update_or_create(
            code=item['code'],
            defaults={
                'discount_type': item['discount_type'],
                'value': item['value'],
                'minimum_subtotal': item['minimum_subtotal'],
                'active': True,
            },
        )

    print('Seed complete')
    print(f'Categories: +{created_categories} created, {updated_categories} updated')
    print(f'Products: +{created_products} created, {updated_products} updated')


if __name__ == '__main__':
    main()
