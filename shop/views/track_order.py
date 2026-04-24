from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET
from django.http import JsonResponse
from .models import Order
from .api_views import _api_error, _api_ok

@require_GET
@csrf_exempt
def track_order(request):
    user = request.user
    if not user.is_authenticated:
        return _api_error("User not authenticated", status=401)

    orders = Order.objects.filter(user=user).select_related('orderstatusevent_set').order_by('-created_at')
    order_data = []

    for order in orders:
        status_events = order.orderstatusevent_set.all().order_by('-timestamp')
        events = [
            {
                "status": event.status,
                "timestamp": event.timestamp,
            }
            for event in status_events
        ]

        order_data.append({
            "order_id": order.id,
            "created_at": order.created_at,
            "total_price": order.total_price,
            "status_events": events,
        })

    return _api_ok({"orders": order_data})