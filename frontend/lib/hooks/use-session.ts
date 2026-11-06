"use client";

import { useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { supabase } from "@/lib/supabase";
import { sessionDeadline } from "@/lib/session-lifetime";

let signingOut: Promise<unknown> | null = null;
function expireSession() {
  signingOut ??= supabase.auth.signOut({ scope: "local" }).catch(() => {}).finally(() => { signingOut = null; });
}

/** The current Supabase session; `ready` is false until the stored session has been read. */
export function useSession() {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    function accept(next: Session | null) {
      if (!active) return;
      clearTimeout(timer);
      const remaining = next ? sessionDeadline(next.access_token) - Date.now() : 0;
      setSession(next && remaining > 0 ? next : null);
      setReady(true);
      if (next) {
        // Defer sign-out outside Supabase's auth-state callback lock.
        timer = setTimeout(() => {
          if (!active) return;
          setSession(null);
          expireSession();
        }, Math.max(0, remaining));
      }
    }
    function check() {
      void supabase.auth.getSession().then(({ data }) => accept(data.session));
    }
    check();
    const { data } = supabase.auth.onAuthStateChange((_event, next) => {
      accept(next);
    });
    window.addEventListener("focus", check);
    document.addEventListener("visibilitychange", check);
    return () => {
      active = false;
      clearTimeout(timer);
      window.removeEventListener("focus", check);
      document.removeEventListener("visibilitychange", check);
      data.subscription.unsubscribe();
    };
  }, []);

  return { session, ready };
}
