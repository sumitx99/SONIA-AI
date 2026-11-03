"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Check, FileSearch, ShieldCheck, X } from "lucide-react";
import { Brand, Emblem } from "@/components/brand";
import { supabase, supabaseConfigured } from "@/lib/supabase";
import { useSession } from "@/lib/hooks/use-session";

interface Request {
  clientName: string;
  redirectHost: string;
  scopes: string[];
}

/**
 * Supabase's OAuth server sends users here (Site URL + Authorization Path) when an app
 * such as Claude asks to connect to Sonia over MCP. The user approves or denies; Supabase
 * then redirects back to that app with a code (or an access_denied error).
 */
export default function OAuthConsentPage() {
  const router = useRouter();
  const { session, ready } = useSession();
  // undefined until the URL has been read; "" when the link has no request id.
  const [authorizationId, setAuthorizationId] = useState<string | undefined>(undefined);
  const [request, setRequest] = useState<Request | null>(null);
  const [busy, setBusy] = useState<"approve" | "deny" | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setAuthorizationId(new URLSearchParams(window.location.search).get("authorization_id") ?? "");
  }, []);

  useEffect(() => {
    if (!ready || authorizationId === undefined) return;
    if (!authorizationId) {
      setError("This link is missing its authorization request. Start the connection again from your app.");
      return;
    }
    if (!session) {
      // Sign in first, then come straight back to this request.
      router.replace(`/auth?next=${encodeURIComponent(`/oauth/consent?authorization_id=${authorizationId}`)}`);
      return;
    }
    let active = true;
    supabase.auth.oauth.getAuthorizationDetails(authorizationId).then(({ data, error: failure }) => {
      if (!active) return;
      if (failure || !data) {
        setError(failure?.message || "This authorization request has expired. Start again from your app.");
      } else if ("authorization_id" in data) {
        let redirectHost = data.redirect_uri;
        try { redirectHost = new URL(data.redirect_uri).host || data.redirect_uri; } catch { /* keep raw */ }
        setRequest({
          clientName: data.client?.name || "An application",
          redirectHost,
          scopes: (data.scope || "").split(" ").filter(Boolean),
        });
      } else {
        // Approved before: Supabase hands back the app's redirect straight away.
        window.location.assign(data.redirect_url);
      }
    });
    return () => { active = false; };
  }, [ready, session, authorizationId, router]);

  async function decide(choice: "approve" | "deny") {
    if (!authorizationId) return;
    setBusy(choice);
    setError("");
    const { error: failure } = choice === "approve"
      ? await supabase.auth.oauth.approveAuthorization(authorizationId)
      : await supabase.auth.oauth.denyAuthorization(authorizationId);
    // On success supabase-js redirects the browser back to the app.
    if (failure) {
      setError(failure.message);
      setBusy(null);
    }
  }

  return (
    <main className="consent-page">
      <div className="consent-brand"><Brand /></div>
      <section className="consent-card" aria-live="polite">
        <Emblem />
        {!supabaseConfigured ? (
          <p className="auth-message auth-error" role="alert">Sign-in isn’t configured on this site.</p>
        ) : error ? (
          <>
            <h1>Can’t connect <em>right now.</em></h1>
            <p className="auth-message auth-error" role="alert">{error}</p>
          </>
        ) : !request ? (
          <p className="consent-loading" role="status">Checking the request…</p>
        ) : (
          <>
            <p className="eyebrow">CONNECT AN APP</p>
            <h1><strong>{request.clientName}</strong> <em>wants to use Sonia.</em></h1>
            <p className="consent-account">Signed in as <strong>{session?.user.email}</strong></p>
            <ul className="consent-list">
              <li><FileSearch size={16} aria-hidden /> Read and search the documents you uploaded</li>
              <li><ShieldCheck size={16} aria-hidden /> It can’t upload, change or delete anything</li>
            </ul>
            <p className="consent-note">
              You’ll return to <strong>{request.redirectHost}</strong>. You can disconnect it at any time
              from Settings.
            </p>
            <div className="consent-actions">
              <button type="button" className="button button-paper" onClick={() => decide("deny")}
                disabled={busy !== null}>
                <X size={16} aria-hidden /> {busy === "deny" ? "Cancelling…" : "Deny"}
              </button>
              <button type="button" className="button button-orange" onClick={() => decide("approve")}
                disabled={busy !== null}>
                <Check size={16} aria-hidden /> {busy === "approve" ? "Connecting…" : "Allow"}
              </button>
            </div>
          </>
        )}
      </section>
    </main>
  );
}
