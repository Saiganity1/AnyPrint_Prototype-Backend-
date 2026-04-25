// Track Order JavaScript for Backend
document.addEventListener('DOMContentLoaded', function() {
    const tabs = document.querySelectorAll('.tab');
    const orderList = document.getElementById('order-list');
    let orders = [];

    // Check authentication
    fetch('/api/auth/me/', {
        credentials: 'include'
    })
    .then(response => response.json())
    .then(data => {
        if (!data.is_authenticated) {
            window.location.href = '/login/';
            return;
        }
        loadOrders();
    })
    .catch(error => {
        console.error('Auth check failed:', error);
        window.location.href = '/login/';
    });

    function loadOrders() {
        fetch('/track-order-api/', {
            credentials: 'include'
        })
        .then(response => response.json())
        .then(data => {
            if (data.orders) {
                orders = data.orders;
                displayOrders('all');
            } else {
                orderList.innerHTML = '<p>No orders found.</p>';
            }
        })
        .catch(error => {
            console.error('Failed to load orders:', error);
            orderList.innerHTML = '<p>Failed to load orders.</p>';
        });
    }

    function displayOrders(status) {
        let filteredOrders = orders;
        if (status !== 'all') {
            filteredOrders = orders.filter(order => getOrderStatus(order) === status);
        }

        if (filteredOrders.length === 0) {
            orderList.innerHTML = '<p>No orders in this category.</p>';
            return;
        }

        orderList.innerHTML = filteredOrders.map(order => `
            <div class="order-card">
                <h3>Order #${order.order_id}</h3>
                <p>Status: ${getOrderStatus(order)}</p>
                <p>Total: PHP ${order.total_price}</p>
                <p>Created: ${new Date(order.created_at).toLocaleDateString()}</p>
            </div>
        `).join('');
    }

    function getOrderStatus(order) {
        const events = order.status_events || [];
        const latestEvent = events[0]; // Assuming ordered by -timestamp
        const status = latestEvent ? latestEvent.status.toLowerCase() : 'pending';
        if (status === 'pending') return 'unpaid';
        if (status === 'confirmed' || status === 'packed') return 'to-ship';
        if (status === 'shipped' || status === 'out_for_delivery') return 'shipping';
        if (status === 'delivered') return 'completed';
        if (status === 'cancelled') return 'cancellation';
        return 'all';
    }

    tabs.forEach(tab => {
        tab.addEventListener('click', function() {
            tabs.forEach(t => t.classList.remove('active'));
            this.classList.add('active');
            const status = this.getAttribute('data-status');
            displayOrders(status);
        });
    });
});