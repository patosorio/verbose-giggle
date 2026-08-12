"use client";

import { use, type ReactNode } from "react";

import { TripRail } from "@/components/trips/TripRail";

interface TripLayoutProps {
  children: ReactNode;
  params: Promise<{ tripId: string }>;
}

// Mounted once for every route under a given trip (page.tsx AND legs/[legId]/page.tsx
// both nest under it) — Next keeps it alive across navigation between them, which is
// what makes TripRail persistent instead of remounting per leg click. A Client
// Component can't be `async`, so `params` (a Promise as of Next 15+) is unwrapped with
// React's `use()` here rather than `await` — same idea, different mechanism because of
// the "use client" boundary.
//
// This div fills AppShell's <main> exactly (h-full = 100% of <main>'s own bounded
// height from components/shared/AppShell.tsx) and never grows past it. That's why its
// overflow-y-auto below and <main>'s own overflow-y-auto don't fight each other:
// <main>'s scroll only ever activates for routes with no nested layout of their own
// (/trips, /trips/new) — whenever a trip route is mounted, this layout's rail and
// content pane are the only two scroll regions in play.
export default function TripLayout({ children, params }: TripLayoutProps) {
  const { tripId } = use(params);

  return (
    <div className="flex h-full min-h-0">
      <TripRail tripId={tripId} />
      <div className="min-w-0 flex-1 overflow-y-auto">{children}</div>
    </div>
  );
}
