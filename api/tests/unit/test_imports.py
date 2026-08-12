"""Phase 5.5 — URL-import (raw HTML) + manual entry (mocked HTTP + Claude)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from anthropic.types import ToolUseBlock
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import AppError
from db.models import (
    BudgetBand,
    ImportedOption,
    Leg,
    LegStatus,
    OptionCard,
    OptionType,
    RawApiResponse,
    RawApiSource,
    Trip,
    TripStatus,
    User,
)
from research.imports import (
    ImportAgentError,
    fetch_page,
    parse_emit_imported_payload,
    research_imported_option,
)
from research.types import ImportedOptionParsed, ParsedImportedOption
from schemas.imports import ManualOptionIn
from schemas.options import ImportedOptionOut
from services.imports import persist_imported_option, persist_manual_option
from services.options import list_options_for_leg

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "imports"
_PRICED_HTML = (_FIXTURES / "priced_page.html").read_text(encoding="utf-8")


async def _seed_leg(session: AsyncSession) -> tuple[Leg, User]:
    user = User(email=f"{uuid4()}@example.com", display_name="Organizer")
    session.add(user)
    await session.flush()
    trip = Trip(
        name="Import test",
        organizer_id=user.id,
        home_currency="THB",
        budget_band=BudgetBand.comfort,
        status=TripStatus.planning,
    )
    session.add(trip)
    await session.flush()
    leg = Leg(
        trip_id=trip.id,
        sequence_index=0,
        origin="Phuket",
        destination="Koh Yao Noi",
        start_date=date(2026, 11, 10),
        end_date=date(2026, 11, 12),
        nights=2,
        filters={},
        status=LegStatus.pending,
    )
    session.add(leg)
    await session.flush()
    return leg, user


def test_no_bs4_import_in_research_imports() -> None:
    import research.imports as imports_mod

    source = Path(imports_mod.__file__).read_text(encoding="utf-8")
    assert "bs4" not in source
    assert "BeautifulSoup" not in source


def test_parse_downgrades_price_without_supporting_quote() -> None:
    option, error = parse_emit_imported_payload(
        {
            "title": "Sunset Cruise",
            "description": "Nice boat",
            "category_hint": "boat tour",
            "estimated_price_amount": "1800",
            "estimated_price_currency": "THB",
            "price_supporting_quote": "",
        }
    )
    assert error is None
    assert option is not None
    assert option.title == "Sunset Cruise"
    assert option.estimated_price_amount is None
    assert option.estimated_price_currency is None


def test_parse_keeps_price_with_supporting_quote() -> None:
    option, error = parse_emit_imported_payload(
        {
            "title": "Sunset Cruise",
            "estimated_price_amount": 1800,
            "estimated_price_currency": "thb",
            "price_supporting_quote": "Price: 1,800 THB per person.",
        }
    )
    assert error is None
    assert option is not None
    assert option.estimated_price_amount == Decimal("1800")
    assert option.estimated_price_currency == "THB"


def test_parse_empty_title_is_extraction_failure() -> None:
    option, error = parse_emit_imported_payload({"title": "   "})
    assert option is None
    assert error is not None
    assert "title" in error


@pytest.mark.asyncio
async def test_fetch_page_returns_raw_html_truncated() -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = _PRICED_HTML

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("research.imports.httpx.AsyncClient", return_value=mock_client):
        text = await fetch_page("https://example.com/cruise")

    assert "<script>" in text
    assert "<style>" in text
    assert "<header>" in text
    assert "<nav>" in text
    assert "<footer>" in text
    assert "Koh Yao Sunset Dinner Cruise" in text
    assert "1,800 THB" in text


@pytest.mark.asyncio
async def test_fetch_page_non_2xx_is_upstream_api_error() -> None:
    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.text = "blocked"

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("research.imports.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(ImportAgentError) as exc_info:
            await fetch_page("https://example.com/blocked")

    assert exc_info.value.status_code == 502
    assert exc_info.value.code == "upstream_api_error"


@pytest.mark.asyncio
async def test_fetch_page_timeout_is_upstream_api_error() -> None:
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("research.imports.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(ImportAgentError) as exc_info:
            await fetch_page("https://example.com/slow")

    assert exc_info.value.status_code == 502
    assert exc_info.value.code == "upstream_api_error"


@pytest.mark.asyncio
async def test_research_passes_raw_html_into_claude_prompt() -> None:
    tool_input: dict[str, object] = {
        "title": "Koh Yao Sunset Dinner Cruise",
        "description": "Three-hour evening cruise with dinner.",
        "category_hint": "boat tour",
        "estimated_price_amount": "1800",
        "estimated_price_currency": "THB",
        "price_supporting_quote": "Price: 1,800 THB per person.",
    }
    real_block = ToolUseBlock(
        type="tool_use",
        id="toolu_test",
        name="emit_imported_option",
        input=tool_input,
    )
    message = MagicMock()
    message.content = [real_block]
    message.model_dump = MagicMock(return_value={"content": [{"input": tool_input}]})

    mock_anthropic = MagicMock()
    mock_anthropic.messages.create = AsyncMock(return_value=message)

    with (
        patch("research.imports.fetch_page", AsyncMock(return_value=_PRICED_HTML)),
        patch("research.imports._client", return_value=mock_anthropic),
        patch("research.imports.settings") as mock_settings,
    ):
        mock_settings.anthropic_api_key = "test-key"
        mock_settings.anthropic_activities_model = "claude-test"
        mock_settings.anthropic_activities_max_tokens = 1024
        parsed = await research_imported_option("https://example.com/cruise")

    assert parsed.extraction_failed is False
    assert parsed.option is not None
    create_kwargs = mock_anthropic.messages.create.await_args.kwargs
    prompt = create_kwargs["messages"][0]["content"]
    assert "<script>" in prompt
    assert "<header>" in prompt
    assert "Koh Yao Sunset Dinner Cruise" in prompt
    assert parsed.response_body["page_text"] == _PRICED_HTML


@pytest.mark.asyncio
async def test_persist_priced_import_uses_caller_tier(
    db_session: AsyncSession,
) -> None:
    leg, _user = await _seed_leg(db_session)
    await db_session.commit()

    parsed = ImportedOptionParsed(
        request_params={"url": "https://example.com/cruise"},
        response_body={"page_text": _PRICED_HTML},
        source_url="https://example.com/cruise",
        option=ParsedImportedOption(
            title="Koh Yao Sunset Dinner Cruise",
            description="Three-hour cruise",
            category_hint="boat tour",
            estimated_price_amount=Decimal("1800"),
            estimated_price_currency="THB",
            price_supporting_quote="Price: 1,800 THB per person.",
        ),
        extraction_failed=False,
        extraction_error=None,
    )

    out = await persist_imported_option(
        db_session,
        leg_id=leg.id,
        tier=BudgetBand.premium,
        parsed=parsed,
    )

    assert out.option_type == OptionType.imported
    assert out.tier == BudgetBand.premium
    assert out.source_url == "https://example.com/cruise"

    card = await db_session.get(OptionCard, out.id)
    assert card is not None
    assert card.raw_response_id is not None
    assert card.research_run_id is None


@pytest.mark.asyncio
async def test_persist_extraction_failed_commits_raw_and_raises_validation_error(
    db_session: AsyncSession,
) -> None:
    leg, _user = await _seed_leg(db_session)
    await db_session.commit()

    parsed = ImportedOptionParsed(
        request_params={"url": "https://example.com/empty"},
        response_body={"page_text": "...", "tool_input": {"title": ""}},
        source_url="https://example.com/empty",
        option=None,
        extraction_failed=True,
        extraction_error="title is empty or whitespace-only",
    )

    with pytest.raises(ImportAgentError) as exc_info:
        await persist_imported_option(
            db_session,
            leg_id=leg.id,
            tier=BudgetBand.comfort,
            parsed=parsed,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "validation_error"

    raws = (
        await db_session.execute(
            select(RawApiResponse).where(
                RawApiResponse.source == RawApiSource.claude_url_extract
            )
        )
    ).scalars().all()
    assert len(raws) == 1


def test_manual_option_in_rejects_empty_title() -> None:
    with pytest.raises(ValidationError):
        ManualOptionIn(tier=BudgetBand.comfort, title="   ")


def test_manual_option_in_rejects_price_without_currency() -> None:
    with pytest.raises(ValidationError):
        ManualOptionIn(
            tier=BudgetBand.comfort,
            title="Cafe",
            price_amount=Decimal("500"),
            price_currency=None,
        )


def test_manual_option_in_rejects_currency_without_price() -> None:
    with pytest.raises(ValidationError):
        ManualOptionIn(
            tier=BudgetBand.comfort,
            title="Cafe",
            price_amount=None,
            price_currency="THB",
        )


@pytest.mark.asyncio
async def test_persist_manual_option_with_price(
    db_session: AsyncSession,
) -> None:
    leg, _user = await _seed_leg(db_session)
    await db_session.commit()

    out = await persist_manual_option(
        db_session,
        leg_id=leg.id,
        body=ManualOptionIn(
            tier=BudgetBand.premium,
            title="Friend's villa",
            description="Already booked",
            category_hint="lodging",
            price_amount=Decimal("3500"),
            price_currency="THB",
        ),
    )

    assert out.option_type == OptionType.imported
    assert out.tier == BudgetBand.premium
    assert out.source_url is None
    assert out.base_price_amount == Decimal("3500")
    assert out.currency == "THB"
    assert out.extracted_title == "Friend's villa"

    card = await db_session.get(OptionCard, out.id)
    assert card is not None
    assert card.raw_response_id is None
    assert card.research_run_id is None

    detail = await db_session.get(ImportedOption, out.id)
    assert detail is not None
    assert detail.source_url is None
    assert detail.estimated_price_amount == Decimal("3500")


@pytest.mark.asyncio
async def test_persist_manual_option_without_price(
    db_session: AsyncSession,
) -> None:
    leg, _user = await _seed_leg(db_session)
    await db_session.commit()

    out = await persist_manual_option(
        db_session,
        leg_id=leg.id,
        body=ManualOptionIn(
            tier=BudgetBand.budget,
            title="Secret beach tip",
            description=None,
            category_hint="beach",
        ),
    )

    assert out.source_url is None
    assert out.base_price_amount is None
    assert out.currency == "THB"
    assert out.tier == BudgetBand.budget

    detail = await db_session.get(ImportedOption, out.id)
    assert detail is not None
    assert detail.source_url is None
    assert detail.estimated_price_amount is None


@pytest.mark.asyncio
async def test_persist_manual_option_service_rejects_price_currency_mismatch(
    db_session: AsyncSession,
) -> None:
    leg, _user = await _seed_leg(db_session)
    await db_session.commit()

    body = ManualOptionIn.model_construct(
        tier=BudgetBand.comfort,
        title="Cafe",
        description=None,
        category_hint=None,
        price_amount=Decimal("100"),
        price_currency=None,
    )
    with pytest.raises(AppError) as exc_info:
        await persist_manual_option(db_session, leg_id=leg.id, body=body)

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "validation_error"


@pytest.mark.asyncio
async def test_list_options_returns_url_imported_and_manual(
    db_session: AsyncSession,
) -> None:
    leg, user = await _seed_leg(db_session)
    await db_session.commit()

    url_out = await persist_imported_option(
        db_session,
        leg_id=leg.id,
        tier=BudgetBand.comfort,
        parsed=ImportedOptionParsed(
            request_params={"url": "https://example.com/cruise"},
            response_body={"page_text": "x"},
            source_url="https://example.com/cruise",
            option=ParsedImportedOption(
                title="URL Cruise",
                description=None,
                category_hint="boat tour",
                estimated_price_amount=Decimal("1800"),
                estimated_price_currency="THB",
                price_supporting_quote="1800 THB",
            ),
            extraction_failed=False,
            extraction_error=None,
        ),
    )
    manual_out = await persist_manual_option(
        db_session,
        leg_id=leg.id,
        body=ManualOptionIn(
            tier=BudgetBand.budget,
            title="Manual tip",
            category_hint="restaurant",
        ),
    )

    listed = await list_options_for_leg(
        db_session,
        leg_id=leg.id,
        viewer_user_id=user.id,
    )
    imported = [c for c in listed if isinstance(c, ImportedOptionOut)]
    by_id = {c.id: c for c in imported}

    assert url_out.id in by_id
    assert by_id[url_out.id].source_url == "https://example.com/cruise"
    assert manual_out.id in by_id
    assert by_id[manual_out.id].source_url is None
