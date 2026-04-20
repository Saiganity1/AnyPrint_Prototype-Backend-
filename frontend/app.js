const API_BASE = window.API_BASE || 'http://127.0.0.1:8000/api';

let products = [];
let categories = [];
let selectedCategory = '';
let cart = JSON.parse(localStorage.getItem('tt_cart') || '{}');

const productsEl = document.getElementById('products');
const categoryChipsEl = document.getElementById('categoryChips');
const cartItemsEl = document.getElementById('cartItems');
const cartCountEl = document.getElementById('cartCount');
const cartPanel = document.getElementById('cartPanel');
const cartButton = document.getElementById('cartButton');
const closeCart = document.getElementById('closeCart');
const checkoutForm = document.getElementById('checkoutForm');
const checkoutStatus = document.getElementById('checkoutStatus');
const authButton = document.getElementById('authButton');
const authPanel = document.getElementById('authPanel');
const closeAuth = document.getElementById('closeAuth');
const authState = document.getElementById('authState');
const authStatus = document.getElementById('authStatus');
const showLoginTab = document.getElementById('showLoginTab');
const showRegisterTab = document.getElementById('showRegisterTab');
const loginForm = document.getElementById('loginForm');
const registerForm = document.getElementById('registerForm');
const logoutButton = document.getElementById('logoutButton');

let currentUser = null;

async function apiFetch(url, options = {}) {
    const config = {
        credentials: 'include',
        ...options,
    };
    return fetch(url, config);
}

function saveCart() {
    localStorage.setItem('tt_cart', JSON.stringify(cart));
    const count = Object.values(cart).reduce((sum, qty) => sum + qty, 0);
    cartCountEl.textContent = String(count);
    renderCart();
}

function addToCart(productId) {
    const key = String(productId);
    const product = products.find((p) => p.id === productId);
    if (!product) return;

    const nextQty = (cart[key] || 0) + 1;
    if (nextQty > product.stock_quantity) {
        alert('Not enough stock.');
        return;
    }

    cart[key] = nextQty;
    saveCart();
}

function removeFromCart(productId) {
    delete cart[String(productId)];
    saveCart();
}

function renderProducts() {
    productsEl.innerHTML = '';
    for (const product of products) {
        const card = document.createElement('article');
        card.className = 'product-card';

        const imageHtml = product.image_url
            ? `<img src="${product.image_url}" alt="${product.name}">`
            : '<div class="placeholder">No image</div>';

        card.innerHTML = `
            ${imageHtml}
            <h3>${product.name}</h3>
            <p class="meta">${product.category || 'Uncategorized'} | Stock: ${product.stock_quantity}</p>
            <p>${product.description}</p>
            <p><strong>PHP ${product.price}</strong></p>
            <button class="btn" ${product.stock_quantity <= 0 ? 'disabled' : ''}>${product.stock_quantity <= 0 ? 'Sold Out' : 'Add to Cart'}</button>
        `;

        const button = card.querySelector('button');
        if (product.stock_quantity > 0) {
            button.addEventListener('click', () => addToCart(product.id));
        }

        productsEl.appendChild(card);
    }
}

function renderCategories() {
    categoryChipsEl.innerHTML = '';

    const all = document.createElement('button');
    all.className = `chip ${selectedCategory ? '' : 'active'}`;
    all.textContent = 'All';
    all.addEventListener('click', () => loadProducts(''));
    categoryChipsEl.appendChild(all);

    for (const category of categories) {
        const chip = document.createElement('button');
        chip.className = `chip ${selectedCategory === category.slug ? 'active' : ''}`;
        chip.textContent = category.name;
        chip.addEventListener('click', () => loadProducts(category.slug));
        categoryChipsEl.appendChild(chip);
    }
}

function renderCart() {
    cartItemsEl.innerHTML = '';
    const ids = Object.keys(cart);
    if (!ids.length) {
        cartItemsEl.innerHTML = '<p class="meta">Cart is empty.</p>';
        return;
    }

    for (const key of ids) {
        const id = Number(key);
        const product = products.find((p) => p.id === id);
        if (!product) continue;

        const qty = cart[key];
        const node = document.createElement('div');
        node.className = 'cart-item';
        node.innerHTML = `
            <p><strong>${product.name}</strong></p>
            <p class="meta">Qty: ${qty} | PHP ${product.price}</p>
            <button class="plain-btn">Remove</button>
        `;
        node.querySelector('button').addEventListener('click', () => removeFromCart(id));
        cartItemsEl.appendChild(node);
    }
}

async function loadCategories() {
    const res = await apiFetch(`${API_BASE}/categories/`);
    const body = await res.json();
    categories = body.categories || [];
    renderCategories();
}

async function loadProducts(category = '') {
    selectedCategory = category;
    const query = category ? `?category=${encodeURIComponent(category)}` : '';
    const res = await apiFetch(`${API_BASE}/products/${query}`);
    const body = await res.json();
    products = body.products || [];
    renderCategories();
    renderProducts();
    renderCart();
}

function setAuthTab(isLogin) {
    loginForm.classList.toggle('hidden', !isLogin);
    registerForm.classList.toggle('hidden', isLogin);
    showLoginTab.classList.toggle('active', isLogin);
    showRegisterTab.classList.toggle('active', !isLogin);
    authStatus.textContent = '';
}

function renderAuthState() {
    if (currentUser) {
        authState.innerHTML = `<p><strong>Signed in as:</strong> ${currentUser.username}</p>`;
        authButton.textContent = currentUser.username;
        logoutButton.classList.remove('hidden');
    } else {
        authState.innerHTML = '<p class="meta">You are browsing as guest.</p>';
        authButton.textContent = 'Login/Register';
        logoutButton.classList.add('hidden');
    }
}

async function refreshAuthState() {
    const res = await apiFetch(`${API_BASE}/auth/me/`);
    const body = await res.json();
    currentUser = body.is_authenticated ? body.user : null;
    renderAuthState();
}

checkoutForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    checkoutStatus.textContent = '';

    const items = Object.entries(cart).map(([productId, quantity]) => ({
        product_id: Number(productId),
        quantity,
    }));

    if (!items.length) {
        checkoutStatus.textContent = 'Your cart is empty.';
        return;
    }

    const formData = new FormData(checkoutForm);
    const payload = {
        full_name: formData.get('full_name'),
        email: formData.get('email'),
        phone: formData.get('phone'),
        address: formData.get('address'),
        payment_method: formData.get('payment_method'),
        notes: formData.get('notes') || '',
        items,
    };

    const res = await apiFetch(`${API_BASE}/orders/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });

    const body = await res.json();
    if (!res.ok) {
        checkoutStatus.textContent = body.error || 'Checkout failed.';
        return;
    }

    cart = {};
    saveCart();

    if (body.redirect_url) {
        window.location.href = body.redirect_url;
        return;
    }

    checkoutStatus.textContent = `Order #${body.order_id} created successfully.`;
});

cartButton.addEventListener('click', () => cartPanel.classList.remove('hidden'));
closeCart.addEventListener('click', () => cartPanel.classList.add('hidden'));
authButton.addEventListener('click', () => authPanel.classList.remove('hidden'));
closeAuth.addEventListener('click', () => authPanel.classList.add('hidden'));
showLoginTab.addEventListener('click', () => setAuthTab(true));
showRegisterTab.addEventListener('click', () => setAuthTab(false));

loginForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    authStatus.textContent = '';
    const formData = new FormData(loginForm);
    const payload = {
        username: formData.get('username'),
        password: formData.get('password'),
    };

    const res = await apiFetch(`${API_BASE}/auth/login/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    const body = await res.json();

    if (!res.ok) {
        authStatus.textContent = body.error || 'Login failed.';
        return;
    }

    currentUser = body.user;
    renderAuthState();
    authStatus.textContent = 'Login successful.';
    loginForm.reset();
});

registerForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    authStatus.textContent = '';
    const formData = new FormData(registerForm);
    const password = String(formData.get('password') || '');
    const confirmPassword = String(formData.get('confirm_password') || '');

    if (password !== confirmPassword) {
        authStatus.textContent = 'Passwords do not match.';
        return;
    }

    const payload = {
        username: formData.get('username'),
        email: formData.get('email'),
        password,
    };

    const res = await apiFetch(`${API_BASE}/auth/register/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    const body = await res.json();

    if (!res.ok) {
        authStatus.textContent = body.error || 'Registration failed.';
        return;
    }

    currentUser = body.user;
    renderAuthState();
    authStatus.textContent = 'Registration successful. You are now logged in.';
    registerForm.reset();
    setAuthTab(true);
});

logoutButton.addEventListener('click', async () => {
    authStatus.textContent = '';
    const res = await apiFetch(`${API_BASE}/auth/logout/`, {
        method: 'POST',
    });
    if (!res.ok) {
        authStatus.textContent = 'Logout failed.';
        return;
    }

    currentUser = null;
    renderAuthState();
    authStatus.textContent = 'Logged out.';
});

saveCart();
setAuthTab(true);
refreshAuthState().then(() => loadCategories().then(() => loadProducts('')));
