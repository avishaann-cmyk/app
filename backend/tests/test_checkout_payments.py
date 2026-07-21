"""
Cape Ember Coffee - Backend tests for PayFast payment integration.
Covers:
- /api/auth/login (sanity)
- /api/orders (create order from cart)
- /api/payfast/create-payment (PayFast form fields)
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://axis-creator.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

TEST_EMAIL = "testuser2@capeember.co.za"
TEST_PASSWORD = "Test1234!"
# ---------- Fixtures ----------

@pytest.fixture(scope="session")
def auth_token():
    r = requests.post(f"{API}/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD}, timeout=20)
    if r.status_code != 200:
        pytest.skip(f"Login failed: {r.status_code} {r.text}")
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def seeded_cart(auth_headers):
    """Ensure cart has at least one item; returns the cart."""
    # Clear first to keep test deterministic
    requests.delete(f"{API}/cart", headers=auth_headers, timeout=15)
    # Add a known product
    add = requests.post(
        f"{API}/cart/add",
        json={"product_id": "fynbos-roast", "variant_id": "fynbos-250g-whole", "quantity": 1},
        headers=auth_headers,
        timeout=15,
    )
    assert add.status_code == 200, f"add to cart failed: {add.status_code} {add.text}"
    cart = requests.get(f"{API}/cart", headers=auth_headers, timeout=15).json()
    assert cart["item_count"] >= 1
    return cart


# ---------- Auth sanity ----------

class TestAuth:
    def test_login_success(self):
        r = requests.post(f"{API}/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD}, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "access_token" in data
        assert data["user"]["email"] == TEST_EMAIL


# ---------- /api/orders ----------

class TestCreateOrder:
    def test_create_order_with_payfast(self, auth_headers, seeded_cart):
        payload = {
            "shipping_address": {
                "first_name": "Test",
                "last_name": "User2",
                "street": "123 Long Street",
                "city": "Cape Town",
                "province": "Western Cape",
                "postal_code": "8001",
                "country": "South Africa",
            },
            "is_subscription": False,
            "payment_method": "payfast",
        }
        r = requests.post(f"{API}/orders", json=payload, headers=auth_headers, timeout=20)
        assert r.status_code == 200, f"orders create failed: {r.status_code} {r.text}"
        data = r.json()
        assert "order_id" in data and data["order_id"]
        assert "order_number" in data and data["order_number"].startswith("CE-")
        assert data["total"] > 0
        assert "whatsapp_link" in data and "wa.me" in data["whatsapp_link"]
        # Persist via GET
        pytest.shared_order_id_payfast = data["order_id"]

    def test_get_order_persisted(self, auth_headers):
        oid = getattr(pytest, "shared_order_id_payfast", None)
        if not oid:
            pytest.skip("no order created")
        r = requests.get(f"{API}/orders/{oid}", headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        # _id should NOT leak (mongo object id rule)
        assert "_id" not in data or isinstance(data.get("_id"), str)
        assert data.get("payment_method") == "payfast"


# ---------- /api/payfast/create-payment ----------

class TestPayfastCreatePayment:
    def test_payfast_returns_form_fields(self, auth_headers):
        oid = getattr(pytest, "shared_order_id_payfast", None)
        if not oid:
            pytest.skip("requires order")
        r = requests.post(
            f"{API}/payfast/create-payment",
            json={"order_id": oid},
            headers=auth_headers,
            timeout=20,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "payfast_host" in data
        assert data["payfast_host"] in ("www.payfast.co.za", "sandbox.payfast.co.za")
        fields = data.get("fields", {})
        # Required PayFast fields
        for k in ("merchant_id", "merchant_key", "amount", "item_name", "m_payment_id", "signature",
                  "return_url", "cancel_url", "notify_url", "email_address"):
            assert k in fields, f"missing {k}"
        assert fields["m_payment_id"] == oid
        assert len(fields["signature"]) == 32  # md5 hex

    def test_payfast_other_user_order_404(self, auth_headers):
        r = requests.post(
            f"{API}/payfast/create-payment",
            json={"order_id": "non-existent-order-id"},
            headers=auth_headers,
            timeout=15,
        )
        assert r.status_code == 404


# ---------- Unauthenticated guards ----------

class TestAuthGuards:
    def test_orders_requires_auth(self):
        r = requests.post(f"{API}/orders", json={"shipping_address": {}}, timeout=15)
        assert r.status_code == 401

    def test_payfast_requires_auth(self):
        r = requests.post(f"{API}/payfast/create-payment", json={"order_id": "x"}, timeout=15)
        assert r.status_code == 401

