import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from .models import Category, Order, Product


class AuthApiTests(TestCase):
	def setUp(self):
		self.client = Client()

	def test_register_and_login_flow(self):
		register_url = reverse('api_auth_register')
		login_url = reverse('api_auth_login')

		register_payload = {
			'username': 'alice',
			'email': 'alice@example.com',
			'password': 'SecurePass123!',
		}
		register_response = self.client.post(register_url, data=json.dumps(register_payload), content_type='application/json')
		self.assertEqual(register_response.status_code, 201)
		register_body = register_response.json()
		self.assertIn('user', register_body)
		self.assertIn('tokens', register_body)

		logout_url = reverse('api_auth_logout')
		self.client.post(logout_url)

		login_response = self.client.post(
			login_url,
			data=json.dumps({'username': 'alice', 'password': 'SecurePass123!'}),
			content_type='application/json',
		)
		self.assertEqual(login_response.status_code, 200)
		login_body = login_response.json()
		self.assertIn('user', login_body)
		self.assertIn('tokens', login_body)

	@patch('shop.api_views.requests.get')
	def test_google_social_login(self, mock_requests_get):
		mock_requests_get.return_value.status_code = 200
		mock_requests_get.return_value.json.return_value = {
			'email': 'google-user@example.com',
			'email_verified': 'true',
			'name': 'Google User',
		}

		response = self.client.post(
			reverse('api_auth_social_login'),
			data=json.dumps({'provider': 'google', 'token': 'google-token-123'}),
			content_type='application/json',
		)
		self.assertEqual(response.status_code, 200)
		body = response.json()
		self.assertIn('user', body)
		self.assertIn('tokens', body)
		self.assertEqual(body.get('auth_provider'), 'google')

	@patch('shop.api_views.requests.get')
	def test_facebook_social_login(self, mock_requests_get):
		mock_requests_get.return_value.status_code = 200
		mock_requests_get.return_value.json.return_value = {
			'id': 'fb-123',
			'email': 'facebook-user@example.com',
			'name': 'Facebook User',
		}

		response = self.client.post(
			reverse('api_auth_social_login'),
			data=json.dumps({'provider': 'facebook', 'token': 'facebook-token-123'}),
			content_type='application/json',
		)
		self.assertEqual(response.status_code, 200)
		body = response.json()
		self.assertIn('user', body)
		self.assertIn('tokens', body)
		self.assertEqual(body.get('auth_provider'), 'facebook')

	def test_phone_otp_request_and_verify_login(self):
		request_response = self.client.post(
			reverse('api_auth_phone_request'),
			data=json.dumps({'phone_number': '09171234567'}),
			content_type='application/json',
		)
		self.assertEqual(request_response.status_code, 200)
		phone_number = '+639171234567'
		otp_code = cache.get(f'auth:phone:otp:{phone_number}')
		self.assertTrue(otp_code)

		register_response = self.client.post(
			reverse('api_auth_phone_verify'),
			data=json.dumps(
				{
					'phone_number': '09171234567',
					'code': str(otp_code),
					'intent': 'register',
					'username': 'phone_user_1',
					'email': 'phone-user@example.com',
				}
			),
			content_type='application/json',
		)
		self.assertEqual(register_response.status_code, 200)
		register_body = register_response.json()
		self.assertIn('user', register_body)
		self.assertIn('tokens', register_body)
		self.assertEqual(register_body.get('auth_provider'), 'phone')

		second_request_response = self.client.post(
			reverse('api_auth_phone_request'),
			data=json.dumps({'phone_number': '09171234567'}),
			content_type='application/json',
		)
		self.assertEqual(second_request_response.status_code, 200)
		second_code = cache.get(f'auth:phone:otp:{phone_number}')
		self.assertTrue(second_code)

		login_response = self.client.post(
			reverse('api_auth_phone_verify'),
			data=json.dumps(
				{
					'phone_number': '09171234567',
					'code': str(second_code),
					'intent': 'login',
				}
			),
			content_type='application/json',
		)
		self.assertEqual(login_response.status_code, 200)
		login_body = login_response.json()
		self.assertIn('user', login_body)
		self.assertIn('tokens', login_body)
		self.assertEqual(login_body.get('auth_provider'), 'phone')


class CheckoutAndOrderTests(TestCase):
	def setUp(self):
		self.client = Client()
		self.category = Category.objects.create(name='Graphic', slug='graphic')
		self.product = Product.objects.create(
			name='Classic Tee',
			slug='classic-tee',
			category=self.category,
			description='Test shirt',
			price='499.00',
			stock_quantity=20,
			is_active=True,
		)
		self.user = User.objects.create_user(username='buyer', password='BuyerPass123!')
		self.client.login(username='buyer', password='BuyerPass123!')

	def _order_items(self):
		return [{'product_id': self.product.id, 'quantity': 2, 'size': 'M', 'color': 'Black'}]

	def test_checkout_quote_works(self):
		quote_url = reverse('api_checkout_quote')
		response = self.client.post(
			quote_url,
			data=json.dumps({'items': self._order_items(), 'address': 'Quezon City'}),
			content_type='application/json',
		)
		self.assertEqual(response.status_code, 200)
		body = response.json()
		self.assertIn('quote', body)
		self.assertIn('total_amount', body['quote'])

	@patch('shop.api_views.send_order_confirmation_email')
	def test_order_creation_and_idempotency(self, mock_confirmation_email):
		order_url = reverse('api_create_order')
		payload = {
			'full_name': 'Buyer One',
			'email': 'buyer@example.com',
			'phone': '09171234567',
			'address': 'Quezon City',
			'payment_method': 'COD',
			'items': self._order_items(),
		}

		first = self.client.post(
			order_url,
			data=json.dumps(payload),
			content_type='application/json',
			HTTP_IDEMPOTENCY_KEY='order-key-1',
		)
		self.assertEqual(first.status_code, 201)
		first_body = first.json()
		self.assertIn('order_id', first_body)

		second = self.client.post(
			order_url,
			data=json.dumps(payload),
			content_type='application/json',
			HTTP_IDEMPOTENCY_KEY='order-key-1',
		)
		self.assertEqual(second.status_code, 200)
		second_body = second.json()
		self.assertTrue(second_body.get('idempotency_replayed'))
		self.assertEqual(first_body['order_id'], second_body['order_id'])
		self.assertEqual(Order.objects.count(), 1)
		self.assertTrue(mock_confirmation_email.called)

	@patch('shop.api_views.create_stripe_checkout_session')
	@patch('shop.api_views.send_order_confirmation_email')
	def test_payment_callback_like_path_with_stripe_redirect(self, mock_confirmation_email, mock_stripe_checkout):
		mock_stripe_checkout.return_value = ('https://checkout.example.com/session/abc', 'stripe-ref-123')
		order_url = reverse('api_create_order')
		payload = {
			'full_name': 'Buyer Stripe',
			'email': 'stripe@example.com',
			'phone': '09170000000',
			'address': 'Makati',
			'payment_method': 'STRIPE',
			'items': self._order_items(),
		}

		response = self.client.post(order_url, data=json.dumps(payload), content_type='application/json')
		self.assertEqual(response.status_code, 201)
		body = response.json()
		self.assertEqual(body['payment_method'], 'STRIPE')
		self.assertTrue(body['redirect_url'])
		self.assertTrue(mock_confirmation_email.called)

	@patch('shop.api_views.send_order_status_email')
	def test_payment_webhook_marks_order_paid(self, mock_status_email):
		order = Order.objects.create(
			user=self.user,
			full_name='Buyer Webhook',
			email='buyer@example.com',
			phone='09171234567',
			address='Quezon City',
			payment_method='STRIPE',
			payment_reference='stripe-ref-999',
			total_amount='499.00',
		)
		webhook_response = self.client.post(
			reverse('api_payment_webhook'),
			data=json.dumps({
				'provider': 'stripe',
				'event_type': 'payment.paid',
				'payment_reference': 'stripe-ref-999',
				'note': 'Stripe webhook verified.',
			}),
			content_type='application/json',
		)
		self.assertEqual(webhook_response.status_code, 200)
		order.refresh_from_db()
		self.assertTrue(order.is_paid)
		self.assertEqual(order.payment_status, Order.PAYMENT_STATUS_PAID)
		self.assertTrue(mock_status_email.called)
