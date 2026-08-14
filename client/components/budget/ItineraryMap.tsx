"use client";

import { useEffect, useRef } from "react";

import "leaflet/dist/leaflet.css";
import { cn } from "@/lib/utils";

export interface ItineraryMapPin {
  lat: number;
  lng: number;
  name: string;
  routeLabel: string;
}

interface ItineraryMapProps {
  pins: ItineraryMapPin[];
  variant: "snapshot" | "full";
  interactive?: boolean;
}

type LeafletModule = typeof import("leaflet") & {
  default?: typeof import("leaflet");
};

function markerFill(el: HTMLElement): string {
  const value = getComputedStyle(el).getPropertyValue("--turquoise").trim();
  return value.length > 0 ? value : "rgb(0, 194, 203)";
}

export function ItineraryMap({
  pins,
  variant,
  interactive = true,
}: ItineraryMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el || pins.length === 0) return;

    let map: import("leaflet").Map | undefined;
    let cancelled = false;

    void import("leaflet").then((mod) => {
      if (cancelled || !containerRef.current) return;
      const leaflet = mod as LeafletModule;
      const L = leaflet.default ?? leaflet;
      const instance = L.map(containerRef.current, {
        scrollWheelZoom: interactive,
        dragging: interactive,
        zoomControl: interactive,
        attributionControl: true,
      });
      if (cancelled) {
        instance.remove();
        return;
      }
      map = instance;
      const fill = markerFill(containerRef.current);
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "&copy; OpenStreetMap",
      }).addTo(map);

      const latLngs: import("leaflet").LatLngExpression[] = [];
      for (const pin of pins) {
        const latLng: import("leaflet").LatLngExpression = [pin.lat, pin.lng];
        latLngs.push(latLng);
        L.circleMarker(latLng, {
          radius: 8,
          color: fill,
          fillColor: fill,
          fillOpacity: 0.9,
          weight: 2,
        })
          .bindPopup(
            `<strong>${escapeHtml(pin.name)}</strong><br/>${escapeHtml(pin.routeLabel)}`
          )
          .addTo(map);
      }
      if (latLngs.length === 1) {
        map.setView(latLngs[0], 12);
      } else {
        map.fitBounds(L.latLngBounds(latLngs), { padding: [24, 24] });
      }
    });

    return () => {
      cancelled = true;
      map?.remove();
    };
  }, [pins, interactive]);

  return (
    <div
      ref={containerRef}
      className={cn(
        "w-full overflow-hidden rounded-card",
        variant === "snapshot" ? "h-[250px]" : "h-[min(70vh,32.5rem)]"
      )}
    />
  );
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
