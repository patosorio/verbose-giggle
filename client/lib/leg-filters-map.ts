import type { LegFiltersFieldsShape } from "@/components/legs/LegFiltersFields";
import type { LegCreateIn } from "@/lib/types";

type ApiFilters = NonNullable<LegCreateIn["filters"]>;

function nonemptyList<T>(values: T[] | undefined): T[] | undefined {
  return values && values.length > 0 ? values : undefined;
}

export function formLegToApiFilters(leg: LegFiltersFieldsShape): ApiFilters {
  const flight: NonNullable<ApiFilters["flight"]> = {};
  if (leg.max_stops !== undefined) flight.max_stops = leg.max_stops;
  if (leg.max_price !== undefined) flight.max_price = leg.max_price;
  if (leg.deep_search !== undefined) flight.deep_search = leg.deep_search;
  if (leg.travel_class !== undefined) flight.travel_class = leg.travel_class;
  if (leg.show_hidden) flight.show_hidden = true;
  if (leg.exclude_basic) flight.exclude_basic = true;
  if (leg.flight_sort_by !== undefined) flight.sort_by = leg.flight_sort_by;
  const include = nonemptyList(leg.include_airlines);
  const exclude = nonemptyList(leg.exclude_airlines);
  if (include) flight.include_airlines = include;
  if (exclude) flight.exclude_airlines = exclude;
  if (leg.bags !== undefined) flight.bags = leg.bags;
  const hasTimes =
    leg.departure_start_hour !== undefined ||
    leg.departure_end_hour !== undefined ||
    leg.arrival_start_hour !== undefined ||
    leg.arrival_end_hour !== undefined;
  if (hasTimes) {
    flight.time_windows = {
      departure_start_hour: leg.departure_start_hour ?? null,
      departure_end_hour: leg.departure_end_hour ?? null,
      arrival_start_hour: leg.arrival_start_hour ?? null,
      arrival_end_hour: leg.arrival_end_hour ?? null,
    };
  }
  if (leg.emissions) flight.emissions = true;
  if (leg.layover_min_minutes !== undefined) {
    flight.layover_min_minutes = leg.layover_min_minutes;
  }
  if (leg.layover_max_minutes !== undefined) {
    flight.layover_max_minutes = leg.layover_max_minutes;
  }
  const conns = nonemptyList(leg.exclude_conns);
  if (conns) flight.exclude_conns = conns;
  if (leg.max_duration_minutes !== undefined) {
    flight.max_duration_minutes = leg.max_duration_minutes;
  }
  if (leg.infants_in_seat !== undefined) flight.infants_in_seat = leg.infants_in_seat;
  if (leg.infants_on_lap !== undefined) flight.infants_on_lap = leg.infants_on_lap;

  const hotel: NonNullable<ApiFilters["hotel"]> = {};
  if (leg.star_class.length > 0) hotel.star_class = leg.star_class;
  if (leg.free_cancellation_only) hotel.free_cancellation_only = true;
  if (leg.special_offers_only) hotel.special_offers_only = true;
  if (leg.eco_certified_only) hotel.eco_certified_only = true;
  if (leg.hotel_price_min !== undefined && leg.hotel_price_max !== undefined) {
    hotel.price_range = {
      min: leg.hotel_price_min,
      max: leg.hotel_price_max,
    };
  }
  const propertyTypes = nonemptyList(leg.property_types);
  if (propertyTypes) hotel.property_types = propertyTypes;
  const amenityIds = nonemptyList(leg.amenity_ids);
  if (amenityIds) hotel.amenity_ids = amenityIds;
  if (leg.min_rating !== undefined) hotel.min_rating = leg.min_rating;
  if (leg.hotel_sort_by !== undefined) hotel.sort_by = leg.hotel_sort_by;
  const brands = nonemptyList(leg.brands);
  if (brands) hotel.brands = brands;
  if (leg.vacation_rentals) hotel.vacation_rentals = true;
  if (leg.bedrooms !== undefined) hotel.bedrooms = leg.bedrooms;
  if (leg.bathrooms !== undefined) hotel.bathrooms = leg.bathrooms;

  const filters: ApiFilters = {
    occupancy: {
      rooms: leg.rooms.map((room) => ({
        adults: room.adults,
        children: room.children,
        children_ages: room.children_ages.slice(0, room.children),
      })),
    },
  };
  if (Object.keys(flight).length > 0) filters.flight = flight;
  if (Object.keys(hotel).length > 0) filters.hotel = hotel;
  return filters;
}

export function apiFiltersToFormFields(
  filters: ApiFilters | undefined
): Partial<LegFiltersFieldsShape> {
  const flight = filters?.flight;
  const hotel = filters?.hotel;
  return {
    max_stops: flight?.max_stops,
    max_price: flight?.max_price,
    deep_search: flight?.deep_search ?? undefined,
    travel_class: flight?.travel_class ?? undefined,
    show_hidden: flight?.show_hidden ?? false,
    exclude_basic: flight?.exclude_basic ?? false,
    flight_sort_by: flight?.sort_by ?? undefined,
    include_airlines: flight?.include_airlines ?? [],
    exclude_airlines: flight?.exclude_airlines ?? [],
    bags: flight?.bags ?? undefined,
    departure_start_hour: flight?.time_windows?.departure_start_hour ?? undefined,
    departure_end_hour: flight?.time_windows?.departure_end_hour ?? undefined,
    arrival_start_hour: flight?.time_windows?.arrival_start_hour ?? undefined,
    arrival_end_hour: flight?.time_windows?.arrival_end_hour ?? undefined,
    emissions: flight?.emissions ?? false,
    layover_min_minutes: flight?.layover_min_minutes ?? undefined,
    layover_max_minutes: flight?.layover_max_minutes ?? undefined,
    exclude_conns: flight?.exclude_conns ?? [],
    max_duration_minutes: flight?.max_duration_minutes ?? undefined,
    infants_in_seat: flight?.infants_in_seat ?? undefined,
    infants_on_lap: flight?.infants_on_lap ?? undefined,
    star_class: hotel?.star_class ?? [],
    free_cancellation_only: hotel?.free_cancellation_only ?? false,
    special_offers_only: hotel?.special_offers_only ?? false,
    eco_certified_only: hotel?.eco_certified_only ?? false,
    hotel_price_min: hotel?.price_range?.min,
    hotel_price_max: hotel?.price_range?.max,
    property_types: hotel?.property_types ?? [],
    amenity_ids: hotel?.amenity_ids ?? [],
    min_rating: hotel?.min_rating ?? undefined,
    hotel_sort_by: hotel?.sort_by ?? undefined,
    brands: hotel?.brands ?? [],
    vacation_rentals: hotel?.vacation_rentals ?? false,
    bedrooms: hotel?.bedrooms ?? undefined,
    bathrooms: hotel?.bathrooms ?? undefined,
  };
}

export function countAdvancedFilters(leg: LegFiltersFieldsShape): number {
  let count = 0;
  const mark = (set: boolean) => {
    if (set) count += 1;
  };
  mark(leg.deep_search !== undefined);
  mark(leg.travel_class !== undefined);
  mark(leg.show_hidden);
  mark(leg.exclude_basic);
  mark(leg.flight_sort_by !== undefined);
  mark((leg.include_airlines?.length ?? 0) > 0);
  mark((leg.exclude_airlines?.length ?? 0) > 0);
  mark(leg.bags !== undefined);
  mark(
    leg.departure_start_hour !== undefined ||
      leg.departure_end_hour !== undefined ||
      leg.arrival_start_hour !== undefined ||
      leg.arrival_end_hour !== undefined
  );
  mark(leg.emissions);
  mark(leg.layover_min_minutes !== undefined || leg.layover_max_minutes !== undefined);
  mark((leg.exclude_conns?.length ?? 0) > 0);
  mark(leg.max_duration_minutes !== undefined);
  mark(leg.infants_in_seat !== undefined || leg.infants_on_lap !== undefined);
  mark((leg.property_types?.length ?? 0) > 0);
  mark((leg.amenity_ids?.length ?? 0) > 0);
  mark(leg.min_rating !== undefined);
  mark(leg.hotel_sort_by !== undefined);
  mark(leg.eco_certified_only);
  mark(leg.special_offers_only);
  mark((leg.brands?.length ?? 0) > 0);
  mark(leg.vacation_rentals);
  mark(leg.bedrooms !== undefined || leg.bathrooms !== undefined);
  return count;
}
