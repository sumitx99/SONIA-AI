"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, Plug, Unplug } from "lucide-react";
import type { OAuthGrant } from "@supabase/supabase-js";
import { supabase } from "@/lib/supabase";

const MCP_URL = `${(process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").trim().replace(/\/+$/, "")}/mcp`;

/** Apps (Claude, Cursor, …) the user allowed to read Sonia over MCP, with a way to cut them off. */
function AppsUsingSonia() {
  const [grants, setGrants] = useState<OAuthGrant[] | null>(null);
  const [error, setError] = useState("");
  const [revoking, setRevoking] = useState<string | null>(null);

  const load = useCallback(async () => {
    const { data, error: failure } = await supabase.auth.oauth.listGrants();
    if (failure) setError("Connected apps couldn’t be loaded. Please try again.");
    else setGrants(data ?? []);
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function revoke(grant: OAuthGrant) {
    setRevoking(grant.client.id);
    setError("");
    const { error: failure } = await supabase.auth.oauth.revokeGrant({ clientId: grant.client.id });
    if (failure) setError(`${grant.client.name || "The app"} couldn’t be disconnected. Please try again.`);
    else setGrants((current) => (current ?? []).filter((item) => item.client.id !== grant.client.id));
    setRevoking(null);
  }

  return (
    <section className="connections-block" aria-labelledby="apps-using-sonia">
      <h4 id="apps-using-sonia">Apps using Sonia</h4>
      <p className="account-section-copy">
        Let Claude, Cursor or another MCP app search your documents. Add this server URL in the app, then
        sign in and allow it:
      </p>
      <code className="connections-url">{MCP_URL}</code>
      {error && <p className="connections-error" role="alert">{error}</p>}
      {grants === null && !error ? (
        <p className="connections-empty"><Loader2 size={14} className="animate-spin" /> Loading connected apps…</p>
      ) : grants && grants.length === 0 ? (
        <p className="connections-empty">No apps are connected yet.</p>
      ) : (
        <ul className="connections-list">
          {(grants ?? []).map((grant) => (
            <li key={grant.client.id}>
              <span className="connections-icon" aria-hidden><Plug size={14} /></span>
              <span className="connections-name">
                <strong>{grant.client.name || "Unnamed app"}</strong>
                <small>Can read your documents · since {new Date(grant.granted_at).toLocaleDateString()}</small>
              </span>
              <button type="button" className="account-secondary-button" disabled={revoking !== null}
                onClick={() => revoke(grant)} aria-label={`Disconnect ${grant.client.name || "this app"}`}>
                {revoking === grant.client.id ? <Loader2 size={13} className="animate-spin" /> : <Unplug size={13} />}
                Disconnect
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function ConnectionsPanel() {
  return (
    <>
      <h3>Connections</h3>
      <AppsUsingSonia />
    </>
  );
}
