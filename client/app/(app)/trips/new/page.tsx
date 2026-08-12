import Link from "next/link";

import { CreateTripForm } from "@/components/trips/CreateTripForm";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export default function NewTripPage() {
  return (
    <div className="mx-auto flex w-full max-w-md flex-col gap-6 p-6">
      <div className="flex flex-col gap-2">
        <Link
          href="/trips"
          className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "w-fit px-0")}
        >
          ← Back to trips
        </Link>
        <h1 className="font-display text-2xl font-bold text-ink">New trip</h1>
      </div>
      <CreateTripForm />
    </div>
  );
}
