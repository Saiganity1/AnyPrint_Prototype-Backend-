import logging
import time

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

logger = logging.getLogger('shop')


class RequestTimingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.perf_counter()
        response = self.get_response(request)
        elapsed_ms = (time.perf_counter() - started) * 1000

        if elapsed_ms >= 250:
            logger.warning('slow_request method=%s path=%s status=%s elapsed_ms=%.2f', request.method, request.path, getattr(response, 'status_code', '?'), elapsed_ms)

        response['X-Response-Time-Ms'] = f'{elapsed_ms:.2f}'
        return response


class JwtAuthMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.jwt = JWTAuthentication()

    def __call__(self, request):
        # Keep session-authenticated users unchanged; only fallback to bearer token.
        user = getattr(request, 'user', None)
        if not user or not getattr(user, 'is_authenticated', False):
            auth_header = request.META.get('HTTP_AUTHORIZATION', '')
            if auth_header.startswith('Bearer '):
                raw_token = auth_header.split(' ', 1)[1].strip()
                if raw_token:
                    try:
                        validated = self.jwt.get_validated_token(raw_token)
                        request.user = self.jwt.get_user(validated)
                    except (InvalidToken, TokenError, Exception):
                        # Invalid tokens are handled by view-level auth checks.
                        pass

        return self.get_response(request)
