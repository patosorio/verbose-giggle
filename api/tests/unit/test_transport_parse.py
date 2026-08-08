"""Unit tests for transport emit parsing + shared price coercion (Phase 4.5)."""

from __future__ import annotations

import logging
from decimal import Decimal

import pytest

from research.transport import parse_emit_transport_payload
from research.types import coerce_estimated_price_amount


def test_coerce_null_passes_through() -> None:
    assert coerce_estimated_price_amount(None) is None


def test_coerce_passes_numeric_unchanged() -> None:
    assert coerce_estimated_price_amount(Decimal("1500")) == Decimal("1500")
    assert coerce_estimated_price_amount(1500) == Decimal("1500")
    assert coerce_estimated_price_amount(1500.5) == Decimal("1500.5")
    assert coerce_estimated_price_amount("1500") == Decimal("1500")


def test_coerce_hyphen_range_to_midpoint(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="research.types"):
        assert coerce_estimated_price_amount("1,000-1,500") == Decimal("1250")
    assert "price range coerced: '1,000-1,500' -> 1250" in caplog.text


def test_coerce_to_range_to_midpoint(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="research.types"):
        assert coerce_estimated_price_amount("1,500 to 1,800") == Decimal("1650")
    assert "price range coerced: '1,500 to 1,800' -> 1650" in caplog.text


@pytest.mark.parametrize("raw", ["N/A", "", "free", "about 1000", "1,000–1,500 USD"])
def test_coerce_garbage_hard_fails(raw: str) -> None:
    with pytest.raises(ValueError, match="invalid estimated_price_amount"):
        coerce_estimated_price_amount(raw)


def test_parse_keeps_priced_unpriced_and_coerced_range() -> None:
    parsed, drop_reasons = parse_emit_transport_payload(
        {
            "options": [
                {
                    "mode": "ferry",
                    "operator_name": "Lomprayah",
                    "departure_point": "Rassada Pier, Phuket",
                    "arrival_point": "Koh Yao Noi Pier",
                    "estimated_duration_minutes": 90,
                    "estimated_price_amount": "1,000-1,500",
                    "estimated_price_currency": "thb",
                    "booking_url": "https://example.com/book",
                    "citations": [
                        {
                            "claim_text": "Ferry 1,000–1,500 THB.",
                            "source_url": "https://example.com/ferry",
                        }
                    ],
                },
                {
                    "mode": "private_van",
                    "operator_name": None,
                    "departure_point": "Phuket Town",
                    "arrival_point": "Koh Yao Noi",
                    "estimated_duration_minutes": 120,
                    "estimated_price_amount": None,
                    "estimated_price_currency": None,
                    "booking_url": None,
                    "citations": [
                        {
                            "claim_text": "Shared vans leave from Phuket Town.",
                            "source_url": "https://example.com/van",
                        }
                    ],
                },
                {
                    "mode": "bus",
                    "departure_point": "Phuket Bus Terminal",
                    "arrival_point": "Krabi",
                    "estimated_price_amount": "N/A",
                    "estimated_price_currency": "THB",
                    "citations": [
                        {
                            "claim_text": "Bus exists.",
                            "source_url": "https://example.com/bus",
                        }
                    ],
                },
            ]
        }
    )
    assert len(parsed) == 2
    assert parsed[0].estimated_price_amount == Decimal("1250")
    assert parsed[0].estimated_price_currency == "THB"
    assert parsed[1].estimated_price_amount is None
    assert parsed[1].estimated_price_currency is None
    assert drop_reasons and "invalid estimated_price_amount" in drop_reasons[0]


def test_parse_drops_zero_citation_priced_and_unpriced() -> None:
    parsed, drop_reasons = parse_emit_transport_payload(
        {
            "options": [
                {
                    "mode": "ferry",
                    "departure_point": "A",
                    "arrival_point": "B",
                    "estimated_price_amount": 500,
                    "estimated_price_currency": "THB",
                    "citations": [],
                },
                {
                    "mode": "train",
                    "departure_point": "C",
                    "arrival_point": "D",
                    "estimated_price_amount": None,
                    "estimated_price_currency": None,
                    "citations": [],
                },
                {
                    "mode": "ferry",
                    "departure_point": "E",
                    "arrival_point": "F",
                    "estimated_price_amount": 400,
                    "estimated_price_currency": "THB",
                    "citations": [
                        {
                            "claim_text": "Real ferry.",
                            "source_url": "https://example.com/ok",
                        }
                    ],
                },
            ]
        }
    )
    assert len(parsed) == 1
    assert parsed[0].departure_point == "E"
    assert len(drop_reasons) == 2


def test_parse_rejects_price_without_currency() -> None:
    parsed, drop_reasons = parse_emit_transport_payload(
        {
            "options": [
                {
                    "mode": "ferry",
                    "departure_point": "A",
                    "arrival_point": "B",
                    "estimated_price_amount": 500,
                    "estimated_price_currency": None,
                    "citations": [
                        {
                            "claim_text": "Ferry exists.",
                            "source_url": "https://example.com/ferry",
                        }
                    ],
                }
            ]
        }
    )
    assert parsed == []
    assert drop_reasons
