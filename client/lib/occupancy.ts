/** Sum adults+children across leg filters.occupancy.rooms — mirrors api `_leg_party_size`. */
export function occupancyPartySize(filters: Record<string, unknown>): number {
  const occupancy = filters.occupancy as
    | { rooms?: { adults?: number; children?: number }[] }
    | undefined;
  const rooms = occupancy?.rooms;
  if (!rooms || rooms.length === 0) return 1;
  const total = rooms.reduce(
    (sum, room) => sum + (room.adults ?? 0) + (room.children ?? 0),
    0
  );
  return total > 0 ? total : 1;
}
