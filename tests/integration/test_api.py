"""
tests/integration/test_api.py — Integration tests for FastAPI endpoints (§8 API Contract).
"""

import uuid
from fastapi.testclient import TestClient


class TestHealthEndpoints:
    def test_health(self, client: TestClient) -> None:
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}

    def test_ready(self, client: TestClient) -> None:
        res = client.get("/ready")
        assert res.status_code in (200, 503)
        assert "status" in res.json()


class TestAuthProtection:
    def test_unauthenticated_request_fails_401(self, unauthenticated_client: TestClient) -> None:
        res = unauthenticated_client.get("/v1/payments?merchant_id=m_001")
        assert res.status_code == 401
        data = res.json()
        assert "error" in data
        assert data["error"]["code"] == "invalid_api_key"

    def test_invalid_api_key_fails_401(self, client: TestClient) -> None:
        res = client.get(
            "/v1/payments?merchant_id=m_001",
            headers={"X-API-Key": "completely-wrong-key"},
        )
        assert res.status_code == 401
        data = res.json()
        assert data["error"]["code"] == "invalid_api_key"


class TestPaymentEndpoints:
    def test_create_payment_authorized(self, client: TestClient) -> None:
        payload = {
            "merchant_id": "m_001",
            "amount_minor": 49900,
            "currency": "INR",
            "card_last4": "4242",
            "terminal_id": "t_07",
        }
        res = client.post("/v1/payments", json=payload)
        assert res.status_code == 201
        data = res.json()
        assert data["merchant_id"] == "m_001"
        assert data["amount_minor"] == 49900
        assert data["currency"] == "INR"
        assert data["status"] == "AUTHORIZED"
        assert data["terminal_id"] == "t_07"
        assert data["failure_reason"] is None
        assert "id" in data

    def test_create_payment_declined_card_0002(self, client: TestClient) -> None:
        payload = {
            "merchant_id": "m_001",
            "amount_minor": 2000,
            "currency": "INR",
            "card_last4": "0002",
        }
        res = client.post("/v1/payments", json=payload)
        assert res.status_code == 201
        data = res.json()
        assert data["status"] == "FAILED"
        assert data["failure_reason"] == "card_declined"

    def test_create_payment_timeout_card_0005(self, client: TestClient) -> None:
        payload = {
            "merchant_id": "m_001",
            "amount_minor": 2000,
            "currency": "INR",
            "card_last4": "0005",
        }
        res = client.post("/v1/payments", json=payload)
        assert res.status_code == 201
        data = res.json()
        assert data["status"] == "FAILED"
        assert data["failure_reason"] == "timeout"

    def test_create_payment_validation_error(self, client: TestClient) -> None:
        payload = {
            "merchant_id": "m_001",
            "amount_minor": -100,  # Invalid: must be > 0
            "currency": "INR",
            "card_last4": "4242",
        }
        res = client.post("/v1/payments", json=payload)
        assert res.status_code == 400
        data = res.json()
        assert data["error"]["code"] == "validation_error"

    def test_create_payment_unknown_merchant(self, client: TestClient) -> None:
        payload = {
            "merchant_id": "m_non_existent",
            "amount_minor": 1000,
            "currency": "INR",
            "card_last4": "4242",
        }
        res = client.post("/v1/payments", json=payload)
        assert res.status_code == 404
        data = res.json()
        assert data["error"]["code"] == "merchant_not_found"

    def test_get_payment(self, client: TestClient) -> None:
        # Create
        res = client.post(
            "/v1/payments",
            json={
                "merchant_id": "m_001",
                "amount_minor": 10000,
                "currency": "INR",
                "card_last4": "4242",
            },
        )
        payment_id = res.json()["id"]

        # Fetch
        get_res = client.get(f"/v1/payments/{payment_id}")
        assert get_res.status_code == 200
        assert get_res.json()["id"] == payment_id

    def test_get_payment_not_found(self, client: TestClient) -> None:
        random_id = str(uuid.uuid4())
        res = client.get(f"/v1/payments/{random_id}")
        assert res.status_code == 404
        data = res.json()
        assert data["error"]["code"] == "payment_not_found"

    def test_capture_and_refund_lifecycle(self, client: TestClient) -> None:
        # 1. Create AUTHORIZED
        create_res = client.post(
            "/v1/payments",
            json={
                "merchant_id": "m_001",
                "amount_minor": 35000,
                "currency": "INR",
                "card_last4": "4242",
            },
        )
        payment_id = create_res.json()["id"]

        # 2. Capture -> 200 CAPTURED
        cap_res = client.post(f"/v1/payments/{payment_id}/capture")
        assert cap_res.status_code == 200
        assert cap_res.json()["status"] == "CAPTURED"

        # 3. Capture idempotent retry -> 200 CAPTURED
        cap_retry = client.post(f"/v1/payments/{payment_id}/capture")
        assert cap_retry.status_code == 200
        assert cap_retry.json()["status"] == "CAPTURED"

        # 4. Refund -> 200 REFUNDED
        ref_res = client.post(f"/v1/payments/{payment_id}/refund")
        assert ref_res.status_code == 200
        assert ref_res.json()["status"] == "REFUNDED"

        # 5. Refund idempotent retry -> 200 REFUNDED
        ref_retry = client.post(f"/v1/payments/{payment_id}/refund")
        assert ref_retry.status_code == 200
        assert ref_retry.json()["status"] == "REFUNDED"

    def test_capture_failure_card_9995(self, client: TestClient) -> None:
        res = client.post(
            "/v1/payments",
            json={
                "merchant_id": "m_001",
                "amount_minor": 15000,
                "currency": "INR",
                "card_last4": "9995",
            },
        )
        payment_id = res.json()["id"]

        cap_res = client.post(f"/v1/payments/{payment_id}/capture")
        assert cap_res.status_code == 200
        assert cap_res.json()["status"] == "FAILED"
        assert cap_res.json()["failure_reason"] == "capture_failed"

    def test_illegal_transition_returns_409(self, client: TestClient) -> None:
        # Create declined payment
        res = client.post(
            "/v1/payments",
            json={
                "merchant_id": "m_001",
                "amount_minor": 5000,
                "currency": "INR",
                "card_last4": "0002",
            },
        )
        payment_id = res.json()["id"]
        assert res.json()["status"] == "FAILED"

        # Capturing FAILED payment must return 409
        cap_res = client.post(f"/v1/payments/{payment_id}/capture")
        assert cap_res.status_code == 409
        data = cap_res.json()
        assert data["error"]["code"] == "illegal_transition"

        # Refunding FAILED payment must return 409
        ref_res = client.post(f"/v1/payments/{payment_id}/refund")
        assert ref_res.status_code == 409
        assert ref_res.json()["error"]["code"] == "illegal_transition"

    def test_list_payments_and_summary(self, client: TestClient) -> None:
        # Create 2 payments
        client.post(
            "/v1/payments",
            json={
                "merchant_id": "m_001",
                "amount_minor": 1000,
                "currency": "INR",
                "card_last4": "4242",
            },
        )
        p2 = client.post(
            "/v1/payments",
            json={
                "merchant_id": "m_001",
                "amount_minor": 2000,
                "currency": "INR",
                "card_last4": "4242",
            },
        ).json()
        client.post(f"/v1/payments/{p2['id']}/capture")

        # List payments
        list_res = client.get("/v1/payments?merchant_id=m_001&limit=10")
        assert list_res.status_code == 200
        list_data = list_res.json()
        assert len(list_data["items"]) >= 2

        # Summary
        sum_res = client.get("/v1/merchants/m_001/summary")
        assert sum_res.status_code == 200
        sum_data = sum_res.json()
        assert sum_data["merchant_id"] == "m_001"
        assert sum_data["total_captured_minor"] >= 2000
        assert sum_data["by_status"]["CAPTURED"] >= 1
