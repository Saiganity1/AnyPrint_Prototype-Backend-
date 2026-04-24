"""Shopee API integration module for syncing products and orders."""

import hashlib
import hmac
import logging
import time
from datetime import datetime, timedelta
from decimal import Decimal

import requests
from django.conf import settings

logger = logging.getLogger('shop')


class ShopeeAPIError(Exception):
    """Raised when Shopee API requests fail."""
    pass


class ShopeeClient:
    """Client for Shopee API interactions."""
    
    BASE_URL = 'https://partner.shopeemall.com/api/v2'
    
    def __init__(self, partner_id=None, partner_key=None, shop_id=None, access_token=None):
        self.partner_id = partner_id or getattr(settings, 'SHOPEE_PARTNER_ID', '')
        self.partner_key = partner_key or getattr(settings, 'SHOPEE_PARTNER_KEY', '')
        self.shop_id = shop_id or getattr(settings, 'SHOPEE_SHOP_ID', '')
        self.access_token = access_token or getattr(settings, 'SHOPEE_ACCESS_TOKEN', '')
    
    def _generate_signature(self, path, timestamp):
        """Generate HMAC-SHA256 signature for Shopee API."""
        base_string = f'{self.partner_id}{path}{timestamp}'
        signature = hmac.new(
            self.partner_key.encode(),
            base_string.encode(),
            hashlib.sha256
        ).hexdigest()
        return signature
    
    def _make_request(self, method, path, data=None):
        """Make authenticated request to Shopee API."""
        if not all([self.partner_id, self.partner_key, self.shop_id, self.access_token]):
            raise ShopeeAPIError('Shopee API credentials not configured in environment variables.')
        
        timestamp = int(time.time())
        signature = self._generate_signature(path, timestamp)
        
        url = f'{self.BASE_URL}{path}'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': self.access_token,
        }
        
        params = {
            'partner_id': self.partner_id,
            'timestamp': timestamp,
            'sign': signature,
            'shop_id': self.shop_id,
        }
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers, params=params, timeout=30)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=headers, params=params, timeout=30)
            else:
                raise ShopeeAPIError(f'Unsupported HTTP method: {method}')
            
            response.raise_for_status()
            return response.json()
        
        except requests.RequestException as e:
            raise ShopeeAPIError(f'Shopee API request failed: {str(e)}')
    
    def get_products(self, cursor=None, page_size=50):
        """Get list of products from Shopee shop."""
        path = '/product/get_item_list'
        data = {'pagination_entries_per_page': page_size}
        if cursor:
            data['pagination_offset'] = cursor
        
        return self._make_request('GET', path, data)
    
    def get_product_detail(self, item_id):
        """Get detailed information about a product."""
        path = '/product/get_item_base_info'
        data = {'item_id': item_id}
        return self._make_request('GET', path, data)
    
    def get_orders(self, status='ALL', create_time_from=None, create_time_to=None, page_size=50):
        """Get orders from Shopee shop."""
        path = '/order/get_order_list'
        data = {
            'order_status': status,
            'page_size': page_size,
        }
        
        if create_time_from:
            data['time_range_field'] = 'create_time'
            data['time_from'] = int(create_time_from.timestamp())
            data['time_to'] = int(create_time_to.timestamp()) if create_time_to else int(time.time())
        
        return self._make_request('GET', path, data)
    
    def get_order_detail(self, order_sn):
        """Get detailed information about an order."""
        path = '/order/get_order_detail'
        data = {'order_sn': order_sn}
        return self._make_request('GET', path, data)
    
    def sync_product_to_shopee(self, product, shop_item_id=None):
        """Sync a local product to Shopee shop (update if exists, create if new)."""
        path = '/product/init_tier_variation' if not shop_item_id else '/product/update_item'
        
        data = {
            'item_name': product.name,
            'description': product.description,
            'category_id': 0,  # Would need to map categories
            'price': float(product.price),
            'stock': product.stock_quantity,
            'images': [],
            'attributes': [],
        }
        
        if product.image:
            data['images'] = [{'url': product.image.url}]
        
        return self._make_request('POST', path, data)
    
    def sync_order_from_shopee(self, order_sn):
        """Fetch and sync a Shopee order to local database."""
        try:
            order_data = self.get_order_detail(order_sn)
            logger.info(f'Synced Shopee order: {order_sn}')
            return order_data
        except ShopeeAPIError as e:
            logger.error(f'Failed to sync Shopee order {order_sn}: {str(e)}')
            raise


def get_shopee_client():
    """Factory function to get initialized Shopee client."""
    return ShopeeClient()
