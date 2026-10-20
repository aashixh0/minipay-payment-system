"""
tests/unit/test_acquirer.py — Unit tests for MockAcquirer and Strategy pattern (§6.2).
"""

import pytest

from minipay.core.config import settings
from minipay.domain.acquirer import MockAcquirer, get_acquirer


class TestMockAcquirerMagicCards:
    """Verify magic card endings produce deterministic outcomes (§6.2)."""

    def test_default_card_4242(self) -> None:
        acq = MockAcquirer(failure_rate=0.0)
        auth = acq.authorize(49900, "INR", "4242")
        assert auth.approved is True
        assert auth.failure_reason is None

        cap = acq.capture("pay-123", "4242")
        assert cap.approved is True
        assert cap.failure_reason is None

        ref = acq.refund("pay-123")
        assert ref.approved is True
        assert ref.failure_reason is None

    def test_decline_card_0002(self) -> None:
        acq = MockAcquirer(failure_rate=0.0)
        auth = acq.authorize(10000, "INR", "0002")
        assert auth.approved is False
        assert auth.failure_reason == "card_declined"

    def test_timeout_card_0005(self) -> None:
        acq = MockAcquirer(failure_rate=0.0)
        auth = acq.authorize(10000, "INR", "0005")
        assert auth.approved is False
        assert auth.failure_reason == "timeout"

    def test_capture_fail_card_9995(self) -> None:
        acq = MockAcquirer(failure_rate=0.0)
        # 9995 authorizes ok
        auth = acq.authorize(25000, "INR", "9995")
        assert auth.approved is True
        assert auth.failure_reason is None

        # but fails on capture
        cap = acq.capture("pay-456", "9995")
        assert cap.approved is False
        assert cap.failure_reason == "capture_failed"

    def test_random_failure_rate(self) -> None:
        # Failure rate = 1.0 forces acquirer_error even on normal card 4242
        acq = MockAcquirer(failure_rate=1.0)
        auth = acq.authorize(1000, "INR", "4242")
        assert auth.approved is False
        assert auth.failure_reason == "acquirer_error"

        cap = acq.capture("pay-789", "4242")
        assert cap.approved is False
        assert cap.failure_reason == "acquirer_error"

        ref = acq.refund("pay-789")
        assert ref.approved is False
        assert ref.failure_reason == "acquirer_error"


class TestAcquirerFactory:
    """Verify factory selects acquirer from config."""

    def test_factory_returns_mock_acquirer(self) -> None:
        acq = get_acquirer()
        assert isinstance(acq, MockAcquirer)

    def test_factory_raises_on_unknown_acquirer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "acquirer", "unknown_provider")
        with pytest.raises(ValueError, match="Unknown acquirer"):
            get_acquirer()
