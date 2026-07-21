"""Tests for PayFast signature generation and create-payment payload handling."""
import sys
import pytest
from starlette.testclient import TestClient

ROOT_DIR = __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

import server


class DummyOrderCollection:
    def __init__(self, order):
        self.order = order

    async def find_one(self, query):
        if query.get("_id") == self.order["_id"] and query.get("user_id") == self.order["user_id"]:
            return self.order
        return None


def _set_payfast_env(monkeypatch, sandbox=False):
    monkeypatch.setenv("PAYFAST_ENABLED", "true")
    monkeypatch.setenv("PAYFAST_SANDBOX", "true" if sandbox else "false")
    monkeypatch.setenv("PAYFAST_MERCHANT_ID", "34064005")
    monkeypatch.setenv("PAYFAST_MERCHANT_KEY", "nfvifv037umoe")
    monkeypatch.setenv("PAYFAST_PASSPHRASE", "Taegan123456")
    monkeypatch.setenv("PAYFAST_SANDBOX_MERCHANT_ID", "10000100")
    monkeypatch.setenv("PAYFAST_SANDBOX_MERCHANT_KEY", "46f0cd694581a")
    monkeypatch.setenv("PAYFAST_SANDBOX_PASSPHRASE", "sandbox-pass")


class TestPayfastSignature:
    def test_generate_signature_matches_payfast_documented_python_example(self):
        data = {
            "merchant_id": "10000100",
            "merchant_key": "46f0cd694581a",
            "return_url": "https://www.example.com",
            "notify_url": "https://www.example.com/notify_url",
            "m_payment_id": "UniqueId",
            "amount": "200",
            "item_name": "test product",
        }

        signature = server.generate_payfast_signature(data, "jt7NOE43FZPn")
        assert signature == "f74a321292f7a839c770d42868e21db1"

    def test_generate_payfast_signature_uses_passphrase_but_does_not_return_it(self, monkeypatch):
        _set_payfast_env(monkeypatch, sandbox=False)
        data = {
            "merchant_id": "34064005",
            "merchant_key": "nfvifv037umoe",
            "return_url": "https://example.com/success",
            "cancel_url": "https://example.com/cancel",
            "notify_url": "https://example.com/notify",
            "m_payment_id": "order-123",
            "amount": "139.00",
            "item_name": "Cape Ember Order CE-000001",
            "email_address": "test@example.com",
            "name_first": "Test",
            "name_last": "User"
        }

        signature = server.generate_payfast_signature(data)
        assert isinstance(signature, str)
        assert len(signature) == 32
        assert signature == server.generate_payfast_signature(data)

    def test_create_payfast_payment_route_returns_signed_fields_without_passphrase(self, monkeypatch):
        _set_payfast_env(monkeypatch, sandbox=False)

        user = {
            "_id": "user-1",
            "email": "test@example.com",
            "first_name": "Test",
            "last_name": "User"
        }
        order = {
            "_id": "order-123",
            "order_number": "CE-000001",
            "user_id": user["_id"],
            "total": 139.00
        }

        monkeypatch.setattr(server, "db", type("DummyDB", (), {"orders": DummyOrderCollection(order)})())
        server.app.dependency_overrides[server.get_current_user] = lambda: user

        client = TestClient(server.app)
        response = client.post("/api/payfast/create-payment", json={"order_id": order["_id"]})

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["payfast_host"] in ("www.payfast.co.za", "sandbox.payfast.co.za")
        fields = data.get("fields", {})
        assert "signature" in fields
        assert "passphrase" not in fields
        assert fields["m_payment_id"] == order["_id"]
        assert fields["amount"] == "139.00"

        # Verify signature consistency for returned fields
        returned_fields = {k: v for k, v in fields.items() if k != "signature"}
        expected_signature = server.generate_payfast_signature(returned_fields)
        assert fields["signature"] == expected_signature

        server.app.dependency_overrides.clear()
