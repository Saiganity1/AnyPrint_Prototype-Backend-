import logging
import time

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
