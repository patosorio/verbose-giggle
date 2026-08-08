import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class BudgetBand(enum.StrEnum):
    budget = "budget"
    comfort = "comfort"
    premium = "premium"


class TripStatus(enum.StrEnum):
    planning = "planning"
    locked = "locked"
    completed = "completed"
    archived = "archived"


class TripMemberRole(enum.StrEnum):
    organizer = "organizer"
    member = "member"


class AgeCategory(enum.StrEnum):
    adult = "adult"
    child = "child"


class LegStatus(enum.StrEnum):
    pending = "pending"
    researching = "researching"
    ready = "ready"
    failed = "failed"


class OptionType(enum.StrEnum):
    flight = "flight"
    hotel = "hotel"
    activity = "activity"
    transport = "transport"
    imported = "imported"


class ResearchRunType(enum.StrEnum):
    flights = "flights"
    hotels = "hotels"
    activities = "activities"
    transport = "transport"
    full = "full"


class TransportMode(enum.StrEnum):
    ferry = "ferry"
    train = "train"
    bus = "bus"
    private_van = "private_van"
    other = "other"


class ResearchRunStatus(enum.StrEnum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class RawApiSource(enum.StrEnum):
    serpapi_flights_search = "serpapi_flights_search"
    serpapi_flights_booking = "serpapi_flights_booking"
    serpapi_hotels_search = "serpapi_hotels_search"
    serpapi_hotels_property = "serpapi_hotels_property"
    claude_web_search = "claude_web_search"
    claude_url_extract = "claude_url_extract"


class ReactionType(enum.StrEnum):
    up = "up"
    down = "down"


class LockEventType(enum.StrEnum):
    locked = "locked"
    unlocked = "unlocked"
    relocked = "relocked"
    marked_booked = "marked_booked"
    unmarked_booked = "unmarked_booked"


def _pg_enum(enum_cls: type[enum.StrEnum], name: str) -> Enum:
    return Enum(
        enum_cls,
        name=name,
        values_callable=lambda members: [member.value for member in members],
        native_enum=True,
    )


budget_band_enum = _pg_enum(BudgetBand, "budget_band")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class MagicLinkToken(Base):
    __tablename__ = "magic_link_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    token_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class Trip(Base):
    __tablename__ = "trips"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    organizer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    home_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    budget_band: Mapped[BudgetBand] = mapped_column(budget_band_enum, nullable=False)
    budget_target_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    status: Mapped[TripStatus] = mapped_column(_pg_enum(TripStatus, "trip_status"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class TripMember(Base):
    __tablename__ = "trip_members"
    __table_args__ = (UniqueConstraint("trip_id", "invited_email", name="uq_trip_members_trip_id_invited_email"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("trips.id"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    invited_email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    role: Mapped[TripMemberRole] = mapped_column(
        _pg_enum(TripMemberRole, "trip_member_role"),
        nullable=False,
    )
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Traveler(Base):
    __tablename__ = "travelers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("trips.id"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    age_category: Mapped[AgeCategory] = mapped_column(
        _pg_enum(AgeCategory, "age_category"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class Leg(Base):
    __tablename__ = "legs"
    __table_args__ = (
        UniqueConstraint("trip_id", "sequence_index", name="uq_legs_trip_id_sequence_index"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("trips.id"),
        nullable=False,
    )
    sequence_index: Mapped[int] = mapped_column(Integer, nullable=False)
    origin: Mapped[str] = mapped_column(String, nullable=False)
    destination: Mapped[str] = mapped_column(String, nullable=False)
    origin_iata: Mapped[str | None] = mapped_column(String(3), nullable=True)
    destination_iata: Mapped[str | None] = mapped_column(String(3), nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    nights: Mapped[int] = mapped_column(Integer, nullable=False)
    filters: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    status: Mapped[LegStatus] = mapped_column(_pg_enum(LegStatus, "leg_status"), nullable=False)


class ResearchRun(Base):
    __tablename__ = "research_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    leg_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("legs.id"),
        nullable=False,
    )
    run_type: Mapped[ResearchRunType] = mapped_column(
        _pg_enum(ResearchRunType, "research_run_type"),
        nullable=False,
    )
    status: Mapped[ResearchRunStatus] = mapped_column(
        _pg_enum(ResearchRunStatus, "research_run_status"),
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    trace_id: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class RawApiResponse(Base):
    __tablename__ = "raw_api_responses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    research_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("research_runs.id"),
        nullable=True,
    )
    source: Mapped[RawApiSource] = mapped_column(_pg_enum(RawApiSource, "raw_api_source"), nullable=False)
    request_params: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    response_body: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OptionCard(Base):
    __tablename__ = "option_cards"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    leg_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("legs.id"),
        nullable=False,
    )
    option_type: Mapped[OptionType] = mapped_column(_pg_enum(OptionType, "option_type"), nullable=False)
    tier: Mapped[BudgetBand | None] = mapped_column(budget_band_enum, nullable=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    base_price_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    raw_response_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("raw_api_responses.id"),
        nullable=False,
    )
    research_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("research_runs.id"),
        nullable=True,
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class FlightOption(Base):
    __tablename__ = "flight_options"

    option_card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("option_cards.id"),
        primary_key=True,
    )
    booking_token: Mapped[str] = mapped_column(String, nullable=False)
    departure_airport: Mapped[str] = mapped_column(String, nullable=False)
    arrival_airport: Mapped[str] = mapped_column(String, nullable=False)
    departure_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    arrival_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    stops: Mapped[int] = mapped_column(Integer, nullable=False)
    airlines: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    layovers: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    bags_included: Mapped[bool] = mapped_column(Boolean, nullable=False)
    emissions_grams: Mapped[int | None] = mapped_column(Integer, nullable=True)


class HotelOption(Base):
    __tablename__ = "hotel_options"

    option_card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("option_cards.id"),
        primary_key=True,
    )
    property_token: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    star_rating: Mapped[Decimal] = mapped_column(Numeric(2, 1), nullable=False)
    gps_lat: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    gps_lng: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    checkin_date: Mapped[date] = mapped_column(Date, nullable=False)
    checkout_date: Mapped[date] = mapped_column(Date, nullable=False)
    free_cancellation: Mapped[bool] = mapped_column(Boolean, nullable=False)
    eco_certified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    amenities: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)


class ActivityOption(Base):
    __tablename__ = "activity_options"

    option_card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("option_cards.id"),
        primary_key=True,
    )
    category: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_price_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    estimated_price_currency: Mapped[str] = mapped_column(String(3), nullable=False)


class TransportOption(Base):
    __tablename__ = "transport_options"

    option_card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("option_cards.id"),
        primary_key=True,
    )
    mode: Mapped[TransportMode] = mapped_column(
        _pg_enum(TransportMode, "transport_mode"),
        nullable=False,
    )
    operator_name: Mapped[str | None] = mapped_column(String, nullable=True)
    departure_point: Mapped[str] = mapped_column(Text, nullable=False)
    arrival_point: Mapped[str] = mapped_column(Text, nullable=False)
    estimated_duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_price_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    estimated_price_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    booking_url: Mapped[str | None] = mapped_column(String, nullable=True)


class ImportedOption(Base):
    __tablename__ = "imported_options"

    option_card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("option_cards.id"),
        primary_key=True,
    )
    source_url: Mapped[str] = mapped_column(String, nullable=False)
    extracted_title: Mapped[str] = mapped_column(String, nullable=False)
    extracted_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_hint: Mapped[str | None] = mapped_column(String, nullable=True)
    estimated_price_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    estimated_price_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)


class Citation(Base):
    __tablename__ = "citations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    option_card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("option_cards.id"),
        nullable=False,
    )
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(String, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BookingSource(Base):
    __tablename__ = "booking_sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    option_card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("option_cards.id"),
        nullable=False,
    )
    seller_name: Mapped[str] = mapped_column(String, nullable=False)
    price_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    deep_link_url: Mapped[str] = mapped_column(String, nullable=False)
    booking_post_data: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    raw_response_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("raw_api_responses.id"),
        nullable=False,
    )
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ttl_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Reaction(Base):
    __tablename__ = "reactions"
    __table_args__ = (
        UniqueConstraint("option_card_id", "user_id", name="uq_reactions_option_card_id_user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    option_card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("option_cards.id"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    reaction_type: Mapped[ReactionType] = mapped_column(
        _pg_enum(ReactionType, "reaction_type"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class Lock(Base):
    __tablename__ = "locks"
    __table_args__ = (
        Index(
            "uq_locks_leg_id_active",
            "leg_id",
            unique=True,
            postgresql_where=text("unlocked_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    leg_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("legs.id"),
        nullable=False,
    )
    option_card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("option_cards.id"),
        nullable=False,
    )
    locked_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    locked_price_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    locked_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    locked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    unlocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_booked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    booked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LockEvent(Base):
    __tablename__ = "lock_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lock_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("locks.id"),
        nullable=False,
    )
    event_type: Mapped[LockEventType] = mapped_column(
        _pg_enum(LockEventType, "lock_event_type"),
        nullable=False,
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
