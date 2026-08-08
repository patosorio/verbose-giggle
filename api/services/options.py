from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from db.models import (
    BookingSource,
    BudgetBand,
    FlightOption,
    HotelOption,
    OptionCard,
    OptionType,
    RawApiResponse,
    RawApiSource,
)
from research.tiering import assign_price_tiers
from research.types import (
    BookingSourcesParsed,
    FlightSearchParsed,
    HotelSearchParsed,
    ParsedBookingSource,
    ParsedFlightOption,
    ParsedHotelOption,
)


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


async def _write_raw_response(
    session: AsyncSession,
    *,
    source: RawApiSource,
    request_params: dict[str, object],
    response_body: dict[str, object],
    research_run_id: UUID | None,
) -> RawApiResponse:
    raw = RawApiResponse(
        research_run_id=research_run_id,
        source=source,
        request_params=request_params,
        response_body=response_body,
        fetched_at=datetime.now(UTC),
    )
    session.add(raw)
    await session.flush()
    return raw


async def persist_flight_search(
    session: AsyncSession,
    *,
    leg_id: UUID,
    parsed: FlightSearchParsed,
    research_run_id: UUID | None,
) -> list[OptionCard]:
    raw = await _write_raw_response(
        session,
        source=RawApiSource.serpapi_flights_search,
        request_params=parsed.request_params,
        response_body=parsed.response_body,
        research_run_id=research_run_id,
    )

    cards: list[OptionCard] = []
    for tier, flight in assign_price_tiers(parsed.flights):
        card = await _persist_flight_option(
            session,
            leg_id=leg_id,
            tier=tier,
            flight=flight,
            raw_response_id=raw.id,
        )
        cards.append(card)
    await session.commit()
    return cards


async def persist_hotel_search(
    session: AsyncSession,
    *,
    leg_id: UUID,
    parsed: HotelSearchParsed,
    research_run_id: UUID | None,
) -> list[OptionCard]:
    raw = await _write_raw_response(
        session,
        source=RawApiSource.serpapi_hotels_search,
        request_params=parsed.request_params,
        response_body=parsed.response_body,
        research_run_id=research_run_id,
    )

    cards: list[OptionCard] = []
    for tier, hotel in assign_price_tiers(parsed.hotels):
        card = await _persist_hotel_option(
            session,
            leg_id=leg_id,
            tier=tier,
            hotel=hotel,
            raw_response_id=raw.id,
        )
        cards.append(card)
    await session.commit()
    return cards


async def persist_booking_sources(
    session: AsyncSession,
    *,
    option_card_id: UUID,
    parsed: BookingSourcesParsed,
    research_run_id: UUID | None = None,
) -> list[BookingSource]:
    source = (
        RawApiSource.serpapi_flights_booking
        if parsed.endpoint == "flights_booking"
        else RawApiSource.serpapi_hotels_property
    )
    raw = await _write_raw_response(
        session,
        source=source,
        request_params=parsed.request_params,
        response_body=parsed.response_body,
        research_run_id=research_run_id,
    )

    now = datetime.now(UTC)
    ttl_expires_at = now + timedelta(seconds=settings.booking_source_ttl_seconds)
    rows: list[BookingSource] = []
    for item in parsed.sources:
        row = _booking_source_row(
            option_card_id=option_card_id,
            item=item,
            raw_response_id=raw.id,
            fetched_at=now,
            ttl_expires_at=ttl_expires_at,
        )
        session.add(row)
        rows.append(row)
    await session.commit()
    return rows


async def _persist_flight_option(
    session: AsyncSession,
    *,
    leg_id: UUID,
    tier: BudgetBand,
    flight: ParsedFlightOption,
    raw_response_id: UUID,
) -> OptionCard:
    card = OptionCard(
        leg_id=leg_id,
        option_type=OptionType.flight,
        tier=tier,
        title=flight.title,
        base_price_amount=flight.price_amount,
        currency=flight.currency,
        raw_response_id=raw_response_id,
    )
    session.add(card)
    await session.flush()
    session.add(
        FlightOption(
            option_card_id=card.id,
            booking_token=flight.booking_token,
            departure_airport=flight.departure_airport,
            arrival_airport=flight.arrival_airport,
            departure_time=_aware(flight.departure_time),
            arrival_time=_aware(flight.arrival_time),
            duration_minutes=flight.duration_minutes,
            stops=flight.stops,
            airlines=flight.airlines,
            layovers=flight.layovers,
            bags_included=flight.bags_included,
            emissions_grams=flight.emissions_grams,
        )
    )
    return card


async def _persist_hotel_option(
    session: AsyncSession,
    *,
    leg_id: UUID,
    tier: BudgetBand,
    hotel: ParsedHotelOption,
    raw_response_id: UUID,
) -> OptionCard:
    card = OptionCard(
        leg_id=leg_id,
        option_type=OptionType.hotel,
        tier=tier,
        title=hotel.title,
        base_price_amount=hotel.price_amount,
        currency=hotel.currency,
        raw_response_id=raw_response_id,
    )
    session.add(card)
    await session.flush()
    session.add(
        HotelOption(
            option_card_id=card.id,
            property_token=hotel.property_token,
            name=hotel.name,
            star_rating=hotel.star_rating,
            gps_lat=hotel.gps_lat,
            gps_lng=hotel.gps_lng,
            checkin_date=hotel.checkin_date,
            checkout_date=hotel.checkout_date,
            free_cancellation=hotel.free_cancellation,
            eco_certified=hotel.eco_certified,
            amenities=hotel.amenities,
        )
    )
    return card


def _booking_source_row(
    *,
    option_card_id: UUID,
    item: ParsedBookingSource,
    raw_response_id: UUID,
    fetched_at: datetime,
    ttl_expires_at: datetime,
) -> BookingSource:
    return BookingSource(
        option_card_id=option_card_id,
        seller_name=item.seller_name,
        price_amount=item.price_amount,
        currency=item.currency,
        deep_link_url=item.deep_link_url,
        booking_post_data=item.booking_post_data,
        raw_response_id=raw_response_id,
        fetched_at=fetched_at,
        ttl_expires_at=ttl_expires_at,
    )
