"""Unit tests for activities estimated_price_amount coercion (Phase 3 amendment)."""

from __future__ import annotations

import logging
from decimal import Decimal

import pytest

from research.activities import coerce_estimated_price_amount, parse_emit_activities_payload


def test_coerce_passes_numeric_unchanged() -> None:
    assert coerce_estimated_price_amount(Decimal("1500")) == Decimal("1500")
    assert coerce_estimated_price_amount(1500) == Decimal("1500")
    assert coerce_estimated_price_amount(1500.5) == Decimal("1500.5")
    assert coerce_estimated_price_amount("1500") == Decimal("1500")


def test_coerce_hyphen_range_to_midpoint(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="research.activities"):
        assert coerce_estimated_price_amount("1,000-1,500") == Decimal("1250")
    assert "price range coerced: '1,000-1,500' -> 1250" in caplog.text


def test_coerce_to_range_to_midpoint(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="research.activities"):
        assert coerce_estimated_price_amount("1,500 to 1,800") == Decimal("1650")
    assert "price range coerced: '1,500 to 1,800' -> 1650" in caplog.text


@pytest.mark.parametrize("raw", ["N/A", "", "free", "about 1000", "1,000–1,500 USD"])
def test_coerce_garbage_hard_fails(raw: str) -> None:
    with pytest.raises(ValueError, match="invalid estimated_price_amount"):
        coerce_estimated_price_amount(raw)


def test_parse_payload_keeps_coerced_range_activity() -> None:
    parsed, drop_reasons = parse_emit_activities_payload(
        {
            "activities": [
                {
                    "title": "Snorkel Trip",
                    "category": "boat tour",
                    "description": "Typically 1,000–1,500 THB.",
                    "duration_minutes": 240,
                    "estimated_price_amount": "1,000-1,500",
                    "estimated_price_currency": "THB",
                    "suggested_timing": "flexible",
                    "citations": [
                        {
                            "claim_text": "Tour 1,000–1,500 THB.",
                            "source_url": "https://example.com/snorkel",
                        }
                    ],
                },
                {
                    "title": "Broken N/A Price",
                    "category": "tour",
                    "description": "No price.",
                    "duration_minutes": 60,
                    "estimated_price_amount": "N/A",
                    "estimated_price_currency": "THB",
                    "suggested_timing": "flexible",
                    "citations": [
                        {
                            "claim_text": "Mentioned without a price.",
                            "source_url": "https://example.com/na",
                        }
                    ],
                },
            ]
        }
    )
    assert [a.title for a in parsed] == ["Snorkel Trip"]
    assert parsed[0].estimated_price_amount == Decimal("1250")
    assert drop_reasons and "Broken N/A Price" not in drop_reasons[0]
    assert "invalid estimated_price_amount" in drop_reasons[0]
