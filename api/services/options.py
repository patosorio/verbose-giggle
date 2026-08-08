from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.errors import AppError
from db.models import (
    ActivityOption,
    AgeCategory,
    BookingSource,
    BudgetBand,
    Citation,
    FlightOption,
    HotelOption,
    Leg,
    Lock,
    OptionCard,
    OptionType,
    RawApiResponse,
    RawApiSource,
    Reaction,
    ReactionType,
    TransportOption,
    Traveler,
    Trip,
)
from research.serpapi import fetch_flight_booking_options, fetch_hotel_property_details
from research.tiering import (
    assign_pooled_price_tiers,
    matches_home_currency,
    partition_price_tiers,
)
from research.types import (
    BookingSourcesParsed,
    FlightSearchParsed,
    HotelSearchParsed,
    ParsedBookingSource,
    ParsedFlightOption,
    ParsedHotelOption,
)
from schemas.options import (
    ActivityOptionOut,
    FlightOptionOut,
    HotelOptionOut,
    OptionCardOut,
    ReactionSummaryOut,
    TransportOptionOut,
)
from services.combined_tiering import (
    apply_option_card_tier_updates,
    build_pool_from_new_and_existing,
    flight_assignments_from_pool,
    flight_untiered_from_pool,
    load_active_priced_option_cards,
    peer_tier_updates_for_eligible,
    untiered_complement_by_identity,
)

# Mirror services/research.py — avoid importing that module (it imports options).
_HOTEL_CHILD_AGE_PLACEHOLDER = 10
_HOTEL_MAX_TRAVELERS = 6


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


async def _trip_home_currency(session: AsyncSession, leg_id: UUID) -> str | None:
    result = await session.execute(
        select(Trip.home_currency).join(Leg, Leg.trip_id == Trip.id).where(Leg.id == leg_id)
    )
    return result.scalar_one_or_none()


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
    tier_assignments: list[tuple[BudgetBand, ParsedFlightOption]] | None = None,
    untiered_home_flights: list[ParsedFlightOption] | None = None,
    retier_existing_transport: bool = True,
) -> list[OptionCard]:
    """Persist flight RawApiResponse + OptionCards.

    When tier_assignments is None (default), tiers are computed by pooling this batch with
    the leg's currently-active priced transport cards (docs/01_architecture.md §4.1).
    When retier_existing_transport is True, UPDATE tier on those peer transport cards
    whose bucket changed. Pass precomputed tier_assignments and retier_existing_transport=
    False for a full run that already pooled flight+transport candidates once.
    Home-currency flights outside the cheapest-9 cut persist with tier=NULL (Bug 3).
    """
    raw = await _write_raw_response(
        session,
        source=RawApiSource.serpapi_flights_search,
        request_params=parsed.request_params,
        response_body=parsed.response_body,
        research_run_id=research_run_id,
    )

    home_currency = await _trip_home_currency(session, leg_id)
    expected = (home_currency or "XXX").upper()

    peer_updates: dict[UUID, BudgetBand | None] = {}
    if tier_assignments is None:
        peer_cards: list[OptionCard] = []
        if retier_existing_transport and home_currency:
            peer_cards = await load_active_priced_option_cards(
                session,
                leg_id=leg_id,
                option_type=OptionType.transport,
                home_currency=home_currency,
            )
        pool = build_pool_from_new_and_existing(
            home_currency=expected,
            new_flights=parsed.flights,
            existing_priced_cards=peer_cards,
        )
        tiers_by_key = assign_pooled_price_tiers(pool)
        assignments = flight_assignments_from_pool(parsed.flights, tiers_by_key)
        untiered_home = flight_untiered_from_pool(
            parsed.flights, tiers_by_key, home_currency=expected
        )
        if retier_existing_transport and peer_cards:
            peer_updates = peer_tier_updates_for_eligible(peer_cards, tiers_by_key)
    else:
        assignments = tier_assignments
        if untiered_home_flights is not None:
            untiered_home = untiered_home_flights
        else:
            untiered_home = untiered_complement_by_identity(
                [f for f in parsed.flights if matches_home_currency(f.currency, expected)],
                assignments,
            )

    cards: list[OptionCard] = []
    for tier, flight in assignments:
        card = await _persist_flight_option(
            session,
            leg_id=leg_id,
            tier=tier,
            flight=flight,
            raw_response_id=raw.id,
            research_run_id=research_run_id,
        )
        cards.append(card)

    for flight in untiered_home:
        card = await _persist_flight_option(
            session,
            leg_id=leg_id,
            tier=None,
            flight=flight,
            raw_response_id=raw.id,
            research_run_id=research_run_id,
        )
        cards.append(card)

    for flight in parsed.flights:
        if matches_home_currency(flight.currency, expected):
            continue
        card = await _persist_flight_option(
            session,
            leg_id=leg_id,
            tier=None,
            flight=flight,
            raw_response_id=raw.id,
            research_run_id=research_run_id,
        )
        cards.append(card)

    if peer_updates:
        await apply_option_card_tier_updates(session, peer_updates)

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

    home_currency = await _trip_home_currency(session, leg_id)
    expected = (home_currency or "XXX").upper()
    home_hotels = [h for h in parsed.hotels if matches_home_currency(h.currency, expected)]
    foreign_hotels = [
        h for h in parsed.hotels if not matches_home_currency(h.currency, expected)
    ]

    tiered, untiered_home = partition_price_tiers(home_hotels)
    cards: list[OptionCard] = []
    for tier, hotel in tiered:
        card = await _persist_hotel_option(
            session,
            leg_id=leg_id,
            tier=tier,
            hotel=hotel,
            raw_response_id=raw.id,
            research_run_id=research_run_id,
        )
        cards.append(card)
    for hotel in untiered_home:
        card = await _persist_hotel_option(
            session,
            leg_id=leg_id,
            tier=None,
            hotel=hotel,
            raw_response_id=raw.id,
            research_run_id=research_run_id,
        )
        cards.append(card)
    for hotel in foreign_hotels:
        card = await _persist_hotel_option(
            session,
            leg_id=leg_id,
            tier=None,
            hotel=hotel,
            raw_response_id=raw.id,
            research_run_id=research_run_id,
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
    tier: BudgetBand | None,
    flight: ParsedFlightOption,
    raw_response_id: UUID,
    research_run_id: UUID | None,
) -> OptionCard:
    card = OptionCard(
        leg_id=leg_id,
        option_type=OptionType.flight,
        tier=tier,
        title=flight.title,
        base_price_amount=flight.price_amount,
        currency=flight.currency,
        raw_response_id=raw_response_id,
        research_run_id=research_run_id,
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
    tier: BudgetBand | None,
    hotel: ParsedHotelOption,
    raw_response_id: UUID,
    research_run_id: UUID | None,
) -> OptionCard:
    card = OptionCard(
        leg_id=leg_id,
        option_type=OptionType.hotel,
        tier=tier,
        title=hotel.title,
        base_price_amount=hotel.price_amount,
        currency=hotel.currency,
        raw_response_id=raw_response_id,
        research_run_id=research_run_id,
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


async def _reaction_summaries(
    session: AsyncSession,
    *,
    card_ids: list[UUID],
    viewer_user_id: UUID,
) -> dict[UUID, ReactionSummaryOut]:
    if not card_ids:
        return {}

    counts_result = await session.execute(
        select(Reaction.option_card_id, Reaction.reaction_type, func.count())
        .where(Reaction.option_card_id.in_(card_ids))
        .group_by(Reaction.option_card_id, Reaction.reaction_type)
    )
    up_counts: dict[UUID, int] = {card_id: 0 for card_id in card_ids}
    down_counts: dict[UUID, int] = {card_id: 0 for card_id in card_ids}
    for card_id, reaction_type, count in counts_result.all():
        if reaction_type == ReactionType.up:
            up_counts[card_id] = count
        else:
            down_counts[card_id] = count

    mine_result = await session.execute(
        select(Reaction.option_card_id, Reaction.reaction_type).where(
            Reaction.option_card_id.in_(card_ids),
            Reaction.user_id == viewer_user_id,
        )
    )
    my_reactions = {card_id: reaction_type for card_id, reaction_type in mine_result.all()}

    return {
        card_id: ReactionSummaryOut(
            up=up_counts.get(card_id, 0),
            down=down_counts.get(card_id, 0),
            my_reaction=my_reactions.get(card_id),
        )
        for card_id in card_ids
    }


async def list_options_for_leg(
    session: AsyncSession,
    *,
    leg_id: UUID,
    viewer_user_id: UUID,
    option_type: OptionType | None = None,
    tier: BudgetBand | None = None,
) -> list[OptionCardOut]:
    """Active options for a leg, plus the actively-locked card even if superseded."""
    leg = await session.get(Leg, leg_id)
    if leg is None:
        raise AppError(404, "not_found", "Leg not found")

    if option_type == OptionType.imported:
        raise AppError(
            400,
            "validation_error",
            "type filter must be flight, hotel, activity, or transport",
        )

    locked_result = await session.execute(
        select(Lock.option_card_id).where(
            Lock.leg_id == leg_id,
            Lock.unlocked_at.is_(None),
        )
    )
    locked_card_id = locked_result.scalar_one_or_none()

    visibility = OptionCard.superseded_at.is_(None)
    if locked_card_id is not None:
        visibility = or_(visibility, OptionCard.id == locked_card_id)

    conditions = [OptionCard.leg_id == leg_id, visibility]
    if option_type is not None:
        conditions.append(OptionCard.option_type == option_type)
    if tier is not None:
        conditions.append(OptionCard.tier == tier)

    cards_result = await session.execute(
        select(OptionCard)
        .where(and_(*conditions))
        .order_by(OptionCard.tier.asc(), OptionCard.base_price_amount.asc().nulls_last())
    )
    cards = list(cards_result.scalars().all())
    if not cards:
        return []

    card_ids = [card.id for card in cards]
    summaries = await _reaction_summaries(
        session,
        card_ids=card_ids,
        viewer_user_id=viewer_user_id,
    )

    flight_ids = [c.id for c in cards if c.option_type == OptionType.flight]
    hotel_ids = [c.id for c in cards if c.option_type == OptionType.hotel]
    activity_ids = [c.id for c in cards if c.option_type == OptionType.activity]
    transport_ids = [c.id for c in cards if c.option_type == OptionType.transport]

    flights: dict[UUID, FlightOption] = {}
    if flight_ids:
        result = await session.execute(
            select(FlightOption).where(FlightOption.option_card_id.in_(flight_ids))
        )
        flights = {row.option_card_id: row for row in result.scalars().all()}

    hotels: dict[UUID, HotelOption] = {}
    if hotel_ids:
        result = await session.execute(
            select(HotelOption).where(HotelOption.option_card_id.in_(hotel_ids))
        )
        hotels = {row.option_card_id: row for row in result.scalars().all()}

    activities: dict[UUID, ActivityOption] = {}
    if activity_ids:
        result = await session.execute(
            select(ActivityOption).where(ActivityOption.option_card_id.in_(activity_ids))
        )
        activities = {row.option_card_id: row for row in result.scalars().all()}

    transports: dict[UUID, TransportOption] = {}
    if transport_ids:
        result = await session.execute(
            select(TransportOption).where(TransportOption.option_card_id.in_(transport_ids))
        )
        transports = {row.option_card_id: row for row in result.scalars().all()}

    out: list[OptionCardOut] = []
    for card in cards:
        summary = summaries[card.id]
        if card.option_type == OptionType.flight:
            detail = flights.get(card.id)
            if detail is None:
                continue
            out.append(
                FlightOptionOut(
                    id=card.id,
                    tier=card.tier,
                    title=card.title,
                    base_price_amount=card.base_price_amount,
                    currency=card.currency,
                    reaction_summary=summary,
                    booking_token=detail.booking_token,
                    departure_airport=detail.departure_airport,
                    arrival_airport=detail.arrival_airport,
                    departure_time=detail.departure_time,
                    arrival_time=detail.arrival_time,
                    duration_minutes=detail.duration_minutes,
                    stops=detail.stops,
                    airlines=list(detail.airlines),
                    layovers=list(detail.layovers),
                    bags_included=detail.bags_included,
                    emissions_grams=detail.emissions_grams,
                )
            )
        elif card.option_type == OptionType.hotel:
            detail_h = hotels.get(card.id)
            if detail_h is None:
                continue
            out.append(
                HotelOptionOut(
                    id=card.id,
                    tier=card.tier,
                    title=card.title,
                    base_price_amount=card.base_price_amount,
                    currency=card.currency,
                    reaction_summary=summary,
                    property_token=detail_h.property_token,
                    name=detail_h.name,
                    star_rating=detail_h.star_rating,
                    gps_lat=detail_h.gps_lat,
                    gps_lng=detail_h.gps_lng,
                    checkin_date=detail_h.checkin_date,
                    checkout_date=detail_h.checkout_date,
                    free_cancellation=detail_h.free_cancellation,
                    eco_certified=detail_h.eco_certified,
                    amenities=list(detail_h.amenities),
                )
            )
        elif card.option_type == OptionType.activity:
            detail_a = activities.get(card.id)
            if detail_a is None:
                continue
            out.append(
                ActivityOptionOut(
                    id=card.id,
                    tier=card.tier,
                    title=card.title,
                    base_price_amount=card.base_price_amount,
                    currency=card.currency,
                    reaction_summary=summary,
                    category=detail_a.category,
                    description=detail_a.description,
                    duration_minutes=detail_a.duration_minutes,
                    estimated_price_amount=detail_a.estimated_price_amount,
                    estimated_price_currency=detail_a.estimated_price_currency,
                )
            )
        elif card.option_type == OptionType.transport:
            detail_t = transports.get(card.id)
            if detail_t is None:
                continue
            out.append(
                TransportOptionOut(
                    id=card.id,
                    tier=card.tier,
                    title=card.title,
                    base_price_amount=card.base_price_amount,
                    currency=card.currency,
                    reaction_summary=summary,
                    mode=detail_t.mode,
                    operator_name=detail_t.operator_name,
                    departure_point=detail_t.departure_point,
                    arrival_point=detail_t.arrival_point,
                    estimated_duration_minutes=detail_t.estimated_duration_minutes,
                    booking_url=detail_t.booking_url,
                )
            )
    return out


async def upsert_reaction(
    session: AsyncSession,
    *,
    option_id: UUID,
    user_id: UUID,
    reaction_type: ReactionType,
) -> ReactionSummaryOut:
    card = await session.get(OptionCard, option_id)
    if card is None:
        raise AppError(404, "not_found", "Option card not found")

    existing_result = await session.execute(
        select(Reaction).where(
            Reaction.option_card_id == option_id,
            Reaction.user_id == user_id,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing is None:
        session.add(
            Reaction(
                option_card_id=option_id,
                user_id=user_id,
                reaction_type=reaction_type,
            )
        )
    else:
        existing.reaction_type = reaction_type

    await session.commit()
    summaries = await _reaction_summaries(
        session,
        card_ids=[option_id],
        viewer_user_id=user_id,
    )
    return summaries[option_id]


async def delete_reaction(
    session: AsyncSession,
    *,
    option_id: UUID,
    user_id: UUID,
) -> ReactionSummaryOut:
    card = await session.get(OptionCard, option_id)
    if card is None:
        raise AppError(404, "not_found", "Option card not found")

    existing_result = await session.execute(
        select(Reaction).where(
            Reaction.option_card_id == option_id,
            Reaction.user_id == user_id,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        await session.delete(existing)
        await session.commit()

    summaries = await _reaction_summaries(
        session,
        card_ids=[option_id],
        viewer_user_id=user_id,
    )
    return summaries[option_id]


async def _hotel_party_for_leg(
    session: AsyncSession,
    *,
    leg_id: UUID,
) -> tuple[int, int, list[int] | None]:
    """Same traveler → hotel guest mapping as services/research.py run_leg_research."""
    trip_id_result = await session.execute(select(Leg.trip_id).where(Leg.id == leg_id))
    trip_id = trip_id_result.scalar_one_or_none()
    if trip_id is None:
        raise AppError(404, "not_found", "Leg not found")

    categories_result = await session.execute(
        select(Traveler.age_category).where(Traveler.trip_id == trip_id)
    )
    adults = 0
    children = 0
    for category in categories_result.scalars().all():
        if category == AgeCategory.adult:
            adults += 1
        else:
            children += 1
    if adults + children == 0:
        adults = 1

    trimmed_adults = adults
    while trimmed_adults + children > _HOTEL_MAX_TRAVELERS and trimmed_adults > 0:
        trimmed_adults -= 1
    children_ages = (
        [_HOTEL_CHILD_AGE_PLACEHOLDER] * children if children else None
    )
    return trimmed_adults, children, children_ages


async def get_or_fetch_booking_sources(
    session: AsyncSession,
    *,
    option_card_id: UUID,
) -> list[BookingSource]:
    card = await session.get(OptionCard, option_card_id)
    if card is None:
        raise AppError(404, "not_found", "Option card not found")
    if card.option_type not in (OptionType.flight, OptionType.hotel):
        raise AppError(
            404,
            "not_found",
            "Booking sources are only available for flight and hotel options",
        )

    now = datetime.now(UTC)
    cached_result = await session.execute(
        select(BookingSource).where(
            BookingSource.option_card_id == option_card_id,
            BookingSource.ttl_expires_at > now,
        )
    )
    cached = list(cached_result.scalars().all())
    if cached:
        return cached

    if card.option_type == OptionType.flight:
        flight = await session.get(FlightOption, option_card_id)
        if flight is None:
            raise AppError(404, "not_found", "Flight option details not found")
        parsed = await fetch_flight_booking_options(
            booking_token=flight.booking_token,
            currency=card.currency,
            leg_id=card.leg_id,
            departure_id=flight.departure_airport,
            arrival_id=flight.arrival_airport,
        )
    else:
        hotel = await session.get(HotelOption, option_card_id)
        if hotel is None:
            raise AppError(404, "not_found", "Hotel option details not found")
        adults, children, children_ages = await _hotel_party_for_leg(
            session, leg_id=card.leg_id
        )
        parsed = await fetch_hotel_property_details(
            property_token=hotel.property_token,
            check_in_date=hotel.checkin_date,
            check_out_date=hotel.checkout_date,
            currency=card.currency,
            adults=adults,
            children=children,
            children_ages=children_ages,
            q=hotel.name,
            leg_id=card.leg_id,
        )

    return await persist_booking_sources(
        session,
        option_card_id=option_card_id,
        parsed=parsed,
        research_run_id=None,
    )


async def get_citations_for_option(
    session: AsyncSession,
    *,
    option_card_id: UUID,
) -> list[Citation]:
    card = await session.get(OptionCard, option_card_id)
    if card is None:
        raise AppError(404, "not_found", "Option card not found")
    if card.option_type not in (OptionType.activity, OptionType.transport):
        raise AppError(
            404,
            "not_found",
            "Citations are only available for activity and transport options",
        )

    result = await session.execute(
        select(Citation)
        .where(Citation.option_card_id == option_card_id)
        .order_by(Citation.retrieved_at.asc())
    )
    return list(result.scalars().all())
