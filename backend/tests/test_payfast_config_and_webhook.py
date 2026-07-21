import os
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks
from starlette.testclient import TestClient

import server


class DummyWebhookCollection:
    def __init__(self):
        self.items = {}

    async def update_one(self, query, update, upsert=False):
        key = (query.get("provider"), query.get("event_key"))
        matched = 1 if key in self.items else 0
        if matched == 0:
            self.items[key] = update.get("$setOnInsert", {}).copy()
        return SimpleNamespace(matched_count=matched)


class DummyOrderCollection:
    def __init__(self, order=None):
        self.order = order
        self.updates = []

    async def find_one(self, query, projection=None):
        if not self.order:
            return None
        order_id = query.get("_id")
        if order_id and order_id != self.order.get("_id"):
            return None

        if query.get("payfast_payment_id"):
            return None

        if projection:
            return {k: self.order.get(k) for k in projection.keys()}
        return self.order

    async def update_one(self, query, update, upsert=False):
        self.updates.append((query, update))
        if query.get("_id") == self.order.get("_id") and "$set" in update:
            self.order.update(update["$set"])
        return SimpleNamespace(modified_count=1)


class DummyPaymentAttempts:
    def __init__(self):
        self.updates = []
        self.inserts = []

    async def update_many(self, query, update):
        self.updates.append((query, update))
        return SimpleNamespace(modified_count=1)

    async def insert_one(self, doc):
        self.inserts.append(doc)
        return SimpleNamespace(inserted_id=doc.get("_id"))


class DummyCoupons:
    async def find_one(self, query):
        return None


class DummyOrdersInsertCollection:
    def __init__(self):
        self.inserted = []
        self.updates = []

    async def insert_one(self, doc):
        self.inserted.append(doc)
        return SimpleNamespace(inserted_id=doc.get("_id"))

    async def update_one(self, query, update, upsert=False):
        self.updates.append((query, update))
        return SimpleNamespace(modified_count=1)


class DummyDBForWebhook:
    def __init__(self, order=None):
        self.orders = DummyOrderCollection(order=order)
        self.payment_attempts = DummyPaymentAttempts()
        self.webhook_events = DummyWebhookCollection()
        self.users = SimpleNamespace(find_one=self._find_user)
        self.carts = SimpleNamespace(update_one=self._update_cart)

    async def _find_user(self, query):
        return None

    async def _update_cart(self, query, update):
        return SimpleNamespace(modified_count=0)


def _set_payfast_env(monkeypatch, sandbox=True):
    monkeypatch.setenv("PAYFAST_ENABLED", "true")
    monkeypatch.setenv("PAYFAST_SANDBOX", "true" if sandbox else "false")
    monkeypatch.setenv("PAYFAST_SANDBOX_MERCHANT_ID", " 10000100 ")
    monkeypatch.setenv("PAYFAST_SANDBOX_MERCHANT_KEY", " 46f0cd694581a ")
    monkeypatch.setenv("PAYFAST_SANDBOX_PASSPHRASE", " sandbox-pass ")
    monkeypatch.setenv("PAYFAST_MERCHANT_ID", " 34064005 ")
    monkeypatch.setenv("PAYFAST_MERCHANT_KEY", " nfvifv037umoe ")
    monkeypatch.setenv("PAYFAST_PASSPHRASE", " live-pass ")


def _build_valid_itn_payload(order_id, payment_status="COMPLETE", amount="189.00"):
    creds = server.get_payfast_credentials()
    payload = {
        "merchant_id": creds["merchant_id"],
        "merchant_key": creds["merchant_key"],
        "m_payment_id": order_id,
        "amount_gross": amount,
        "payment_status": payment_status,
        "item_name": "Cape Ember Order",
        "pf_payment_id": "PF-TEST-123",
    }
    payload["signature"] = server.generate_payfast_signature(payload, creds["passphrase"])
    return payload


def _client_without_lifespan(monkeypatch):
    monkeypatch.setattr(server.app.router, "on_startup", [])
    monkeypatch.setattr(server.app.router, "on_shutdown", [])
    return TestClient(server.app)


def test_sandbox_true_selects_sandbox_host(monkeypatch):
    _set_payfast_env(monkeypatch, sandbox=True)
    config = server.get_payfast_config()
    assert config["environment"] == "sandbox"
    assert config["process_host"] == "sandbox.payfast.co.za"
    assert config["action_url"] == "https://sandbox.payfast.co.za/eng/process"


def test_sandbox_false_selects_live_host(monkeypatch):
    _set_payfast_env(monkeypatch, sandbox=False)
    config = server.get_payfast_config()
    assert config["environment"] == "production"
    assert config["process_host"] == "www.payfast.co.za"


@pytest.mark.parametrize("bad_value", ["", "maybe"])
def test_unknown_or_empty_sandbox_value_fails(monkeypatch, bad_value):
    monkeypatch.setenv("PAYFAST_ENABLED", "true")
    monkeypatch.setenv("PAYFAST_SANDBOX", bad_value)
    with pytest.raises(server.PayFastConfigurationError):
        server.get_payfast_config()


def test_sandbox_mode_never_falls_back_to_production(monkeypatch):
    _set_payfast_env(monkeypatch, sandbox=True)
    config = server.get_payfast_config()
    assert config["merchant_id"] == "10000100"
    assert config["merchant_key"] == "46f0cd694581a"
    assert config["passphrase"] == "sandbox-pass"


def test_production_mode_never_uses_sandbox_credentials(monkeypatch):
    _set_payfast_env(monkeypatch, sandbox=False)
    config = server.get_payfast_config()
    assert config["merchant_id"] == "34064005"
    assert config["merchant_key"] == "nfvifv037umoe"
    assert config["passphrase"] == "live-pass"


def test_whitespace_is_trimmed(monkeypatch):
    _set_payfast_env(monkeypatch, sandbox=True)
    config = server.get_payfast_config()
    assert config["merchant_id"] == "10000100"
    assert config["merchant_key"] == "46f0cd694581a"
    assert config["passphrase"] == "sandbox-pass"


def test_missing_sandbox_credentials_fail(monkeypatch):
    monkeypatch.setenv("PAYFAST_ENABLED", "true")
    monkeypatch.setenv("PAYFAST_SANDBOX", "true")
    monkeypatch.setenv("PAYFAST_SANDBOX_MERCHANT_ID", "")
    monkeypatch.setenv("PAYFAST_SANDBOX_MERCHANT_KEY", "")
    with pytest.raises(server.PayFastConfigurationError):
        server.get_payfast_config()


def test_malformed_itn_returns_400_not_500(monkeypatch):
    _set_payfast_env(monkeypatch, sandbox=True)
    dummy_db = DummyDBForWebhook(order=None)
    monkeypatch.setattr(server, "db", dummy_db)
    client = _client_without_lifespan(monkeypatch)

    resp = client.post(
        "/api/webhooks/payfast",
        data={"ping": "1"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 400


def test_missing_signature_returns_400(monkeypatch):
    _set_payfast_env(monkeypatch, sandbox=True)
    dummy_db = DummyDBForWebhook(order={"_id": "ord-1", "total": 189.0, "payment_status": "pending"})
    monkeypatch.setattr(server, "db", dummy_db)
    client = _client_without_lifespan(monkeypatch)

    payload = {
        "merchant_id": "10000100",
        "merchant_key": "46f0cd694581a",
        "m_payment_id": "ord-1",
        "amount_gross": "189.00",
        "payment_status": "COMPLETE",
    }
    resp = client.post(
        "/api/webhooks/payfast",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 400


def test_invalid_signature_returns_400(monkeypatch):
    _set_payfast_env(monkeypatch, sandbox=True)
    dummy_db = DummyDBForWebhook(order={"_id": "ord-1", "total": 189.0, "payment_status": "pending"})
    monkeypatch.setattr(server, "db", dummy_db)
    client = _client_without_lifespan(monkeypatch)

    payload = {
        "merchant_id": "10000100",
        "merchant_key": "46f0cd694581a",
        "m_payment_id": "ord-1",
        "amount_gross": "189.00",
        "payment_status": "COMPLETE",
        "signature": "bad-signature",
    }
    resp = client.post(
        "/api/webhooks/payfast",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 400


def test_unknown_order_handled_deliberately(monkeypatch):
    _set_payfast_env(monkeypatch, sandbox=True)
    dummy_db = DummyDBForWebhook(order=None)
    monkeypatch.setattr(server, "db", dummy_db)
    client = _client_without_lifespan(monkeypatch)

    payload = _build_valid_itn_payload("unknown-order")
    resp = client.post(
        "/api/webhooks/payfast",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 404


def test_repeated_valid_itn_is_idempotent(monkeypatch):
    _set_payfast_env(monkeypatch, sandbox=True)
    order = {
        "_id": "ord-2",
        "total": 189.0,
        "payment_status": "pending",
        "payment_method": "payfast",
        "order_number": "CE-TEST-1",
        "guest_email": None,
    }
    dummy_db = DummyDBForWebhook(order=order)
    monkeypatch.setattr(server, "db", dummy_db)
    client = _client_without_lifespan(monkeypatch)

    payload = _build_valid_itn_payload("ord-2")
    resp_first = client.post(
        "/api/webhooks/payfast",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp_second = client.post(
        "/api/webhooks/payfast",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert resp_first.status_code == 200
    assert resp_second.status_code == 200
    paid_updates = [u for _, u in dummy_db.orders.updates if u.get("$set", {}).get("payment_status") == "complete"]
    assert len(paid_updates) == 1


def test_checkout_creation_keeps_pending_payment(monkeypatch):
    _set_payfast_env(monkeypatch, sandbox=True)

    async def fake_get_or_create_cart(user_id, session_id):
        return {"items": [{"product_id": "p1", "variant_id": "v1", "quantity": 1}], "coupon_code": None}

    async def fake_get_store_rules():
        return {"shipping_fee": 50.0, "free_shipping_threshold": 399.0}

    def fake_resolve_tax_config(settings):
        return {"taxRate": 0.15, "taxRegistrationStatus": "registered", "pricesIncludeTax": True}

    def fake_resolve_shipping_charge(**kwargs):
        return {
            "final_delivery_rate": 50.0,
            "original_delivery_rate": 50.0,
            "waived_amount": 0.0,
            "applied_rule": "standard",
            "reason": "default",
        }

    def fake_calculate_vat_components(subtotal_after_discount, tax_config):
        gross = round(float(subtotal_after_discount), 2)
        net = round(gross / 1.15, 2)
        vat = round(gross - net, 2)
        return {"gross": gross, "net": net, "vat": vat}

    monkeypatch.setattr(server, "get_or_create_cart", fake_get_or_create_cart)
    monkeypatch.setattr(server, "get_store_rules", fake_get_store_rules)
    monkeypatch.setattr(server, "resolve_tax_config", fake_resolve_tax_config)
    monkeypatch.setattr(server, "resolve_shipping_charge", fake_resolve_shipping_charge)
    monkeypatch.setattr(server, "calculate_vat_components", fake_calculate_vat_components)

    monkeypatch.setattr(
        server,
        "PRODUCTS_MAP",
        {
            "p1": {
                "id": "p1",
                "name": "Test Coffee",
                "images": [{"url": "https://example.com/p1.png"}],
                "variants": [{"id": "v1", "name": "250g", "sku": "SKU-1", "price": 139.0, "stock_quantity": 10}],
            }
        },
    )

    orders_collection = DummyOrdersInsertCollection()
    payment_attempts = DummyPaymentAttempts()
    dummy_db = SimpleNamespace(
        coupons=DummyCoupons(),
        settings=SimpleNamespace(find_one=lambda query: None),
        orders=orders_collection,
        payment_attempts=payment_attempts,
    )

    async def fake_settings_find_one(query):
        return {}

    dummy_db.settings.find_one = fake_settings_find_one
    monkeypatch.setattr(server, "db", dummy_db)

    checkout = server.CheckoutCreate(
        shipping=server.ShippingInfo(
            method=server.ShippingMethod.STANDARD,
            address=server.AddressModel(
                first_name="Sandbox",
                last_name="Tester",
                street="1 Test Lane",
                apartment="",
                city="Cape Town",
                province="Western Cape",
                postal_code="8001",
                country="South Africa",
                phone="+27820000000",
            ),
            notes="test",
        ),
        billing=server.BillingInfo(same_as_shipping=True, address=None),
        payment_method=server.PaymentMethod.PAYFAST,
        coupon_code=None,
        is_guest=True,
        guest_email="sandbox@example.com",
        is_subscription=False,
    )

    response = asyncio.run(
        server.create_checkout(
            checkout=checkout,
            background_tasks=BackgroundTasks(),
            user=None,
            session_id="sess-1",
        )
    )

    assert response["payment"]["action_url"] == "https://sandbox.payfast.co.za/eng/process"
    assert len(orders_collection.inserted) == 1
    assert orders_collection.inserted[0]["status"] == server.OrderStatus.PENDING_PAYMENT
    updated_status_values = [u[1].get("$set", {}).get("status") for u in orders_collection.updates]
    assert server.OrderStatus.PAYMENT_PROCESSING.value not in updated_status_values


def test_return_status_route_cannot_mark_order_paid(monkeypatch):
    order = {
        "_id": "ord-status-1",
        "order_number": "CE-STAT-1",
        "status": "pending_payment",
        "payment_status": "pending",
        "status_token": "tok-1",
    }

    class DummyStatusOrders:
        def __init__(self, row):
            self.row = row
            self.update_called = False

        async def find_one(self, query, projection=None):
            if query.get("_id") != self.row["_id"]:
                return None
            if projection:
                return {k: self.row.get(k) for k in projection.keys()}
            return self.row

        async def update_one(self, query, update):
            self.update_called = True
            return None

    dummy_orders = DummyStatusOrders(order)
    monkeypatch.setattr(server, "db", SimpleNamespace(orders=dummy_orders))

    result = asyncio.run(server.get_order_status("ord-status-1", status_token="tok-1", user=None))
    assert result["payment_status"] == "pending"
    assert not dummy_orders.update_called
