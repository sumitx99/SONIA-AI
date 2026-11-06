"use client";

import { useSession } from "@/lib/hooks/use-session";

/** Keep the absolute session deadline active on public pages as well as in chat. */
export function SessionLifetime() {
  useSession();
  return null;
}
