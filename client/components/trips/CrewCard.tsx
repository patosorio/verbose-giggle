"use client";

import { toast } from "sonner";

import { AddTravelerForm } from "@/components/trips/AddTravelerForm";
import { Button } from "@/components/ui/button";
import {
  useDeleteTraveler,
  useRemoveMember,
  useTripMembers,
} from "@/hooks/use-trips";
import { ApiError } from "@/lib/api-client";
import type { TravelerOut } from "@/lib/types";

interface CrewCardProps {
  travelers: TravelerOut[];
  organizerName: string | null;
  isOrganizer: boolean;
  tripId: string;
}

// Display panel (docs/07_design_spec.md §5) — lock-authority model + traveler/member
// roster. organizerName resolves only when the current viewer IS the organizer:
// TravelerOut carries no user_id, so there's no way to look up any other viewer's
// display_name for trip.organizer_id from data available on the frontend.
export function CrewCard({
  travelers,
  organizerName,
  isOrganizer,
  tripId,
}: CrewCardProps) {
  const travelerCount = travelers.length;
  const travelerLabel = travelerCount === 1 ? "1 traveler" : `${travelerCount} travelers`;
  const membersQuery = useTripMembers(isOrganizer ? tripId : "");
  const removeMember = useRemoveMember(tripId);
  const deleteTraveler = useDeleteTraveler(tripId);
  const members = membersQuery.data ?? [];

  async function handleRemoveMember(memberId: string) {
    try {
      await removeMember.mutateAsync(memberId);
      toast.success("Member removed.");
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "Could not remove this member."
      );
    }
  }

  async function handleRemoveTraveler(travelerId: string, name: string) {
    try {
      await deleteTraveler.mutateAsync(travelerId);
      toast.success(`${name} removed.`);
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "Could not remove this traveler."
      );
    }
  }

  return (
    <div className="relative overflow-hidden rounded-panel bg-turquoise p-[22px] text-white">
      <span className="pointer-events-none absolute -right-2.5 -bottom-2.5 text-7xl" aria-hidden>
        🌴
      </span>
      <p className="relative max-w-[180px] font-display text-base font-extrabold">
        {travelerLabel} · 1 organizer
      </p>
      <p className="relative mt-1.5 max-w-[170px] text-sm text-white/90">
        {organizerName ?? "The trip organizer"} can lock decisions — everyone else reacts and
        votes.
      </p>

      {travelers.length > 0 && (
        <ul className="relative mt-4 flex flex-col gap-2">
          {travelers.map((traveler) => (
            <li
              key={traveler.id}
              className="flex items-center justify-between gap-2 text-sm"
            >
              <span className="min-w-0 truncate">
                {traveler.name}
                <span className="ml-1.5 text-white/75">· {traveler.age_category}</span>
              </span>
              {isOrganizer && (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  aria-label={`Remove ${traveler.name}`}
                  disabled={deleteTraveler.isPending}
                  className="shrink-0 text-white hover:bg-white/15 hover:text-white"
                  onClick={() => handleRemoveTraveler(traveler.id, traveler.name)}
                >
                  ×
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}

      {isOrganizer ? (
        <>
          <AddTravelerForm tripId={tripId} />
          {members.length > 0 && (
            <ul className="relative mt-4 flex flex-col gap-2 border-t border-white/30 pt-3">
              <li className="text-xs font-bold tracking-wide text-white/80 uppercase">
                Account members
              </li>
              {members.map((member) => (
                <li
                  key={member.id}
                  className="flex items-center justify-between gap-2 text-sm"
                >
                  <span className="min-w-0 truncate">
                    {member.invited_email}
                    <span className="ml-1.5 text-white/75">· {member.role}</span>
                  </span>
                  {member.role !== "organizer" && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-xs"
                      aria-label={`Remove ${member.invited_email}`}
                      disabled={removeMember.isPending}
                      className="shrink-0 text-white hover:bg-white/15 hover:text-white"
                      onClick={() => handleRemoveMember(member.id)}
                    >
                      ×
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </>
      ) : (
        <p className="relative mt-5 text-center text-xs text-white/80">
          Only the trip organizer can add travelers.
        </p>
      )}
    </div>
  );
}
