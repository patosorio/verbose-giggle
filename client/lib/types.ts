/** API response types — mirrored from api/schemas/ (Pydantic). Decimals arrive as JSON strings. */

export type BudgetBand = "budget" | "comfort" | "premium";
export type TripStatus = "planning" | "locked" | "completed" | "archived";
export type LegStatus = "pending" | "researching" | "ready" | "failed";
export type AgeCategory = "adult" | "child";
export type OptionType = "flight" | "hotel" | "activity" | "transport" | "imported";
export type TransportMode = "ferry" | "train" | "bus" | "private_van" | "other";
export type ReactionType = "up" | "down";
export type ResearchRunType =
  | "full"
  | "flights"
  | "hotels"
  | "activities"
  | "transport";

export interface TripSummaryOut {
  id: string;
  name: string;
  organizer_id: string;
  home_currency: string;
  budget_band: BudgetBand;
  budget_target_amount: string | null;
  status: TripStatus;
  created_at: string;
}

export interface TripOut {
  id: string;
  name: string;
  organizer_id: string;
  home_currency: string;
  budget_band: BudgetBand;
  budget_target_amount: string | null;
  status: TripStatus;
  created_at: string;
}

export interface TripCreateIn {
  name: string;
  home_currency: string;
  budget_band: BudgetBand;
  budget_target_amount: number | null;
}

export interface TripPatchIn {
  name?: string;
  budget_band?: BudgetBand;
  budget_target_amount?: number | null;
}

export interface TripMemberCreateIn {
  email: string;
}

export interface TripMemberOut {
  id: string;
  trip_id: string;
  user_id: string | null;
  invited_email: string;
  role: "organizer" | "member";
  joined_at: string | null;
}

export interface TravelerCreateIn {
  name: string;
  age_category: AgeCategory;
}

export interface TravelerOut {
  id: string;
  trip_id: string;
  name: string;
  age_category: AgeCategory;
  created_at: string;
}

export interface LegOut {
  id: string;
  trip_id: string;
  sequence_index: number;
  origin: string;
  destination: string;
  origin_iata: string | null;
  destination_iata: string | null;
  start_date: string;
  end_date: string;
  nights: number;
  filters: Record<string, unknown>;
  skip_hotel: boolean;
  skip_flight: boolean;
  status: LegStatus;
}

/** Wizard / POST /trips/{id}/legs:bulk — filters default empty server-side. */
export interface LegCreateIn {
  sequence_index: number;
  origin: string;
  destination: string;
  origin_iata?: string | null;
  destination_iata?: string | null;
  start_date: string;
  end_date: string;
  skip_hotel?: boolean;
  skip_flight?: boolean;
  /** Only fields Prompt 1 wires into SerpApi — omit empty sub-objects. */
  filters?: {
    flight?: {
      max_stops?: number;
      max_price?: number;
    };
    hotel?: {
      star_class?: number[];
      free_cancellation_only?: boolean;
      price_range?: { min: number; max: number };
    };
    occupancy?: {
      rooms: {
        adults: number;
        children: number;
        children_ages: number[];
      }[];
    };
  };
}

export interface LegBulkCreateIn {
  legs: LegCreateIn[];
}

/** PATCH /legs/{leg_id} — mirrors api/schemas/legs.py LegPatchIn. */
export interface LegPatchIn {
  start_date?: string;
  end_date?: string;
  origin_iata?: string | null;
  destination_iata?: string | null;
  filters?: LegCreateIn["filters"];
  skip_hotel?: boolean;
  skip_flight?: boolean;
}

export interface ResearchStartOut {
  run_id: string;
  status: string;
}

export interface LockedOptionSummaryOut {
  option_card_id: string;
  option_type: OptionType;
  title: string;
  tier: BudgetBand | null;
  amount: string;
  currency: string;
  is_booked: boolean;
  booked_at: string | null;
  unit_price_amount: string | null;
  party_size: number | null;
  room_label: string | null;
}

export interface BudgetLegOut {
  leg_id: string;
  locked_option_ids: string[];
  locked_options: LockedOptionSummaryOut[];
  amount: string | null;
}

export interface BudgetOut {
  home_currency: string;
  budget_band: BudgetBand;
  budget_target_amount: string | null;
  running_total: string;
  by_leg: BudgetLegOut[];
}

export interface ReactionSummaryOut {
  up: number;
  down: number;
  my_reaction: ReactionType | null;
}

export interface ReactionIn {
  reaction_type: ReactionType;
}

export interface BookingSourceOut {
  seller_name: string;
  price_amount: string;
  currency: string;
  deep_link_url: string;
  booking_post_data: Record<string, unknown> | null;
  fetched_at: string;
}

export interface CitationOut {
  claim_text: string;
  source_url: string;
  retrieved_at: string;
}

export interface LockIn {
  option_card_id: string;
}

export interface LockOut {
  id: string;
  leg_id: string;
  option_card_id: string;
  locked_by_user_id: string;
  locked_price_amount: string;
  locked_currency: string;
  locked_at: string;
  unlocked_at: string | null;
  is_booked: boolean;
  booked_at: string | null;
}

export interface PriceAdjustIn {
  new_price_amount: number;
  new_currency?: string | null;
  note?: string | null;
}

interface OptionCardCoreOut {
  id: string;
  tier: BudgetBand | null;
  title: string;
  base_price_amount: string | null;
  currency: string;
  original_price_amount: string | null;
  original_currency: string | null;
  fx_rate: string | null;
  fx_rate_as_of: string | null;
  reaction_summary: ReactionSummaryOut;
}

export interface FlightOptionOut extends OptionCardCoreOut {
  option_type: "flight";
  booking_token: string;
  departure_airport: string;
  arrival_airport: string;
  departure_time: string;
  arrival_time: string;
  duration_minutes: number;
  stops: number;
  airlines: string[];
  layovers: Record<string, unknown>[];
  bags_included: boolean;
  emissions_grams: number | null;
}

export interface HotelOptionOut extends OptionCardCoreOut {
  option_type: "hotel";
  property_token: string;
  name: string;
  star_rating: string;
  gps_lat: string;
  gps_lng: string;
  checkin_date: string;
  checkout_date: string;
  free_cancellation: boolean;
  eco_certified: boolean;
  amenities: string[];
  room_label: string | null;
}

export interface ActivityOptionOut extends OptionCardCoreOut {
  option_type: "activity";
  category: string;
  description: string;
  duration_minutes: number | null;
  estimated_price_amount: string;
  estimated_price_currency: string;
}

export interface TransportOptionOut extends OptionCardCoreOut {
  option_type: "transport";
  mode: TransportMode;
  operator_name: string | null;
  departure_point: string;
  arrival_point: string;
  estimated_duration_minutes: number | null;
  booking_url: string | null;
}

export interface ImportedOptionOut extends OptionCardCoreOut {
  option_type: "imported";
  source_url: string | null;
  extracted_title: string;
  extracted_description: string | null;
  category_hint: string | null;
}

/** POST /legs/{leg_id}/options/manual — mirrors api/schemas/imports.py ManualOptionIn. */
export interface ManualOptionIn {
  tier: BudgetBand;
  title: string;
  description: string | null;
  category_hint: string | null;
  price_amount: number | null;
  price_currency: string | null;
}

export type OptionCardOut =
  | FlightOptionOut
  | HotelOptionOut
  | ActivityOptionOut
  | TransportOptionOut
  | ImportedOptionOut;

/** POST /advisor/messages — mirrors api/schemas/advisor.py */
export interface AirportCandidateOut {
  iata: string;
  name: string;
  city: string;
  country: string;
}

/** GET /airports/resolve — mirrors api/schemas/airports.py */
export interface AirportResolveOut {
  resolved_iata: string | null;
  candidates: AirportCandidateOut[];
}

export interface AdvisorMessageIn {
  role: "user" | "assistant";
  content: string;
}

export interface AdvisorLegIn {
  origin: string;
  destination: string;
  start_date: string | null;
  end_date: string | null;
  filters?: LegCreateIn["filters"];
  skip_hotel?: boolean;
  skip_flight?: boolean;
  locked?: boolean;
}

export interface ProposedLegOut extends AdvisorLegIn {
  origin_iata: string | null;
  origin_candidates: AirportCandidateOut[];
  destination_iata: string | null;
  destination_candidates: AirportCandidateOut[];
}

export interface AdvisorTurnIn {
  messages: AdvisorMessageIn[];
  current_legs: AdvisorLegIn[];
  /** Finalized legs — read-only context; omitted from model revise set. */
  locked_legs?: AdvisorLegIn[];
  trip_name: string | null;
  home_currency: string | null;
  budget_band: BudgetBand | null;
  budget_target_amount: number | null;
}

export interface AdvisorTurnResponse {
  action: "ask" | "revise";
  reply: string;
  questions: string[];
  legs: ProposedLegOut[];
  trip_name: string | null;
  home_currency: string | null;
  budget_band: BudgetBand | null;
  budget_target_amount: number | null | string;
}
