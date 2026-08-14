/** Mirror of api/research/google_hotels_filters.py — keep IDs in lockstep. */

export interface FilterIdName {
  id: number;
  name: string;
}

export const HOSTEL_PROPERTY_TYPE_ID = 14;

export const HOTEL_PROPERTY_TYPES: FilterIdName[] = [
  { id: 12, name: "Beach hotels" },
  { id: 13, name: "Boutique hotels" },
  { id: 14, name: "Hostels" },
  { id: 15, name: "Inns" },
  { id: 16, name: "Motels" },
  { id: 17, name: "Resorts" },
  { id: 18, name: "Spa hotels" },
  { id: 19, name: "Bed and breakfasts" },
  { id: 20, name: "Other" },
  { id: 21, name: "Apartment hotels" },
  { id: 22, name: "Minshuku" },
  { id: 23, name: "Japanese-style business hotels" },
  { id: 24, name: "Ryokan" },
];

export const HOTEL_AMENITIES: FilterIdName[] = [
  { id: 1, name: "Free parking" },
  { id: 3, name: "Parking" },
  { id: 4, name: "Indoor pool" },
  { id: 5, name: "Outdoor pool" },
  { id: 6, name: "Pool" },
  { id: 7, name: "Fitness center" },
  { id: 8, name: "Restaurant" },
  { id: 9, name: "Free breakfast" },
  { id: 10, name: "Spa" },
  { id: 11, name: "Beach access" },
  { id: 12, name: "Child-friendly" },
  { id: 15, name: "Bar" },
  { id: 19, name: "Pet-friendly" },
  { id: 22, name: "Room service" },
  { id: 35, name: "Free Wi-Fi" },
  { id: 40, name: "Air-conditioned" },
  { id: 52, name: "All-inclusive available" },
  { id: 53, name: "Wheelchair accessible" },
  { id: 61, name: "EV charger" },
];

export const VR_PROPERTY_TYPES: FilterIdName[] = [
  { id: 1, name: "Apartments" },
  { id: 2, name: "Bungalows" },
  { id: 3, name: "Cabins" },
  { id: 4, name: "Chalets" },
  { id: 5, name: "Cottages" },
  { id: 6, name: "Gîtes" },
  { id: 7, name: "Holiday villages" },
  { id: 8, name: "Houses" },
  { id: 9, name: "Houseboats" },
  { id: 10, name: "Villas" },
  { id: 11, name: "Other" },
  { id: 21, name: "Apartment hotels" },
];

export const VR_AMENITIES: FilterIdName[] = [
  { id: 2, name: "Hot tub" },
  { id: 4, name: "Air-conditioned" },
  { id: 6, name: "Outdoor grill" },
  { id: 10, name: "Fireplace" },
  { id: 12, name: "Patio or deck" },
  { id: 15, name: "Kitchen" },
  { id: 16, name: "Fitness centre" },
  { id: 18, name: "Cot" },
  { id: 20, name: "Beach access" },
  { id: 21, name: "Child-friendly" },
  { id: 24, name: "Pet-friendly" },
  { id: 29, name: "Free Wi-Fi" },
  { id: 32, name: "Pool" },
];
