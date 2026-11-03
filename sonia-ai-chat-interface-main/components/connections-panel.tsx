"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Loader2, Plug, Plus, RefreshCw, Server, Trash2, Unplug } from "lucide-react";
import type { OAuthGrant } from "@supabase/supabase-js";
import { supabase } from "@/lib/supabase";
import {
  addMcpConnection, deleteMcpConnection, handleApiError, listMcpConnections, mcpOAuthStatus,
  refreshMcpConnection, startMcpOAuth, updateMcpConnection, type McpConnection, type ToolPolicy,
} from "@/lib/api";

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

const POLICY_LABELS: Record<ToolPolicy, string> = { allow: "Always allow", ask: "Ask first", off: "Off" };

function ConnectionCard({ connection, onChange, onRemove }: {
  connection: McpConnection; onChange: (next: McpConnection) => void; onRemove: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");

  async function run(label: string, action: () => Promise<McpConnection | void>) {
    setBusy(label);
    setError("");
    try {
      const next = await action();
      if (next) onChange(next);
    } catch (failure) {
      setError(handleApiError(failure));
    } finally {
      setBusy(null);
    }
  }

  return (
    <li className="mcp-connection">
      <div className="mcp-connection-head">
        <span className="connections-icon" aria-hidden><Server size={14} /></span>
        <span className="connections-name">
          <strong>{connection.name}</strong>
          <small>{connection.url}</small>
        </span>
        <label className="mcp-switch">
          <input type="checkbox" checked={connection.enabled} disabled={busy !== null}
            onChange={(event) => run("toggle", () => updateMcpConnection(connection.id, { enabled: event.target.checked }))} />
          <span>{connection.enabled ? "On" : "Off"}</span>
        </label>
      </div>
      {(error || connection.last_error) && <p className="connections-error" role="alert">{error || connection.last_error}</p>}
      {connection.tools.length === 0 ? (
        <p className="connections-empty">This server offers no tools.</p>
      ) : (
        <ul className="mcp-tools">
          {connection.tools.map((tool) => (
            <li key={tool.name}>
              <span className="mcp-tool-name">
                <strong>{tool.title}</strong>
                <small>{tool.read_only ? "Reads only" : tool.destructive ? "Can change or delete data" : "Can make changes"}</small>
              </span>
              <select value={tool.policy} disabled={busy !== null} aria-label={`When Sonia may use ${tool.title}`}
                onChange={(event) => run(`policy-${tool.name}`, () => updateMcpConnection(connection.id,
                  { tool_policies: { [tool.name]: event.target.value as ToolPolicy } }))}>
                {(Object.keys(POLICY_LABELS) as ToolPolicy[]).map((policy) => (
                  <option key={policy} value={policy}>{POLICY_LABELS[policy]}</option>
                ))}
              </select>
            </li>
          ))}
        </ul>
      )}
      <div className="mcp-connection-actions">
        <button type="button" className="account-secondary-button" disabled={busy !== null}
          onClick={() => run("refresh", () => refreshMcpConnection(connection.id))}>
          {busy === "refresh" ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />} Refresh tools
        </button>
        <button type="button" className="account-secondary-button" disabled={busy !== null}
          onClick={() => run("remove", async () => { await deleteMcpConnection(connection.id); onRemove(); })}>
          {busy === "remove" ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />} Remove
        </button>
      </div>
    </li>
  );
}

function AddConnectionForm({ onAdded }: { onAdded: (connection: McpConnection) => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [auth, setAuth] = useState<"none" | "header" | "oauth">("none");
  const useHeader = auth === "header";
  const [headerName, setHeaderName] = useState("Authorization");
  const [headerValue, setHeaderValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    if (auth === "oauth") {
      // Open the window now, while the click still counts as a user gesture (popup blockers).
      const popup = window.open("about:blank", "sonia-mcp-signin", "width=520,height=720");
      try {
        const { flow_id, authorization_url } = await startMcpOAuth({ name: name.trim(), url: url.trim() });
        if (popup) popup.location.href = authorization_url; else window.open(authorization_url, "_blank");
        const deadline = Date.now() + 10 * 60 * 1000;
        while (Date.now() < deadline) {
          await new Promise((resolve) => setTimeout(resolve, 2000));
          const status = await mcpOAuthStatus(flow_id);
          if (status.status === "done" && status.connection) {
            onAdded(status.connection);
            setOpen(false);
            setName(""); setUrl(""); setAuth("none");
            return;
          }
          if (status.status === "error") throw new Error(status.error || "Signing in didn’t complete");
        }
        throw new Error("Signing in took too long. Please try again.");
      } catch (failure) {
        popup?.close();
        setError(handleApiError(failure));
      } finally {
        setBusy(false);
      }
      return;
    }
    try {
      onAdded(await addMcpConnection({
        name: name.trim(), url: url.trim(), auth_type: useHeader ? "header" : "none",
        ...(useHeader && { header_name: headerName.trim(), header_value: headerValue }),
      }));
      setOpen(false);
      setName(""); setUrl(""); setHeaderValue(""); setAuth("none");
    } catch (failure) {
      setError(handleApiError(failure));
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button type="button" className="account-secondary-button" onClick={() => setOpen(true)}>
        <Plus size={13} /> Add a server
      </button>
    );
  }
  return (
    <form className="mcp-add-form" onSubmit={submit}>
      <label><span>Name</span>
        <input value={name} onChange={(event) => setName(event.target.value)} required maxLength={60} placeholder="My notes" />
      </label>
      <label><span>Server URL</span>
        <input value={url} onChange={(event) => setUrl(event.target.value)} required type="url" inputMode="url"
          placeholder="https://example.com/mcp" />
      </label>
      <fieldset className="mcp-auth-choice">
        <legend>How does the server sign you in?</legend>
        {([["none", "No sign-in"], ["header", "API key or token"], ["oauth", "Sign in with the service (OAuth)"]] as const)
          .map(([value, label]) => (
            <label key={value} className="mcp-check">
              <input type="radio" name="mcp-auth" value={value} checked={auth === value} onChange={() => setAuth(value)} />
              <span>{label}</span>
            </label>
          ))}
      </fieldset>
      {useHeader && (
        <div className="mcp-header-fields">
          <label><span>Header</span>
            <input value={headerName} onChange={(event) => setHeaderName(event.target.value)} required pattern="[A-Za-z0-9-]+" />
          </label>
          <label><span>Value</span>
            <input value={headerValue} onChange={(event) => setHeaderValue(event.target.value)} required type="password"
              autoComplete="off" placeholder="Bearer …" />
          </label>
        </div>
      )}
      <p className="connections-empty">Sonia connects now to check the server and list its tools. Keys are stored encrypted.</p>
      {error && <p className="connections-error" role="alert">{error}</p>}
      <div className="mcp-connection-actions">
        <button type="button" className="account-secondary-button" onClick={() => setOpen(false)} disabled={busy}>Cancel</button>
        <button type="submit" className="account-save-button" disabled={busy}>
          {busy && <Loader2 size={14} className="animate-spin" />}
          {busy ? (auth === "oauth" ? "Waiting for sign-in…" : "Connecting…") : auth === "oauth" ? "Sign in" : "Connect"}
        </button>
      </div>
    </form>
  );
}

/** Remote MCP servers whose tools Sonia may use while answering. */
function SoniasConnections() {
  const [connections, setConnections] = useState<McpConnection[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    listMcpConnections().then(setConnections).catch((failure) => setError(handleApiError(failure)));
  }, []);

  return (
    <section className="connections-block" aria-labelledby="sonias-connections">
      <h4 id="sonias-connections">Tools Sonia can use</h4>
      <p className="account-section-copy">
        Connect a remote MCP server and Sonia can use its tools while answering. Tools that only read run on
        their own; anything that can make changes asks you first.
      </p>
      {error && <p className="connections-error" role="alert">{error}</p>}
      {connections === null && !error ? (
        <p className="connections-empty"><Loader2 size={14} className="animate-spin" /> Loading connections…</p>
      ) : (
        <ul className="connections-list">
          {(connections ?? []).map((connection) => (
            <ConnectionCard key={connection.id} connection={connection}
              onChange={(next) => setConnections((list) => (list ?? []).map((c) => (c.id === next.id ? next : c)))}
              onRemove={() => setConnections((list) => (list ?? []).filter((c) => c.id !== connection.id))} />
          ))}
        </ul>
      )}
      <AddConnectionForm onAdded={(connection) => setConnections((list) => [...(list ?? []), connection])} />
    </section>
  );
}

export function ConnectionsPanel() {
  return (
    <>
      <h3>Connections</h3>
      <SoniasConnections />
      <AppsUsingSonia />
    </>
  );
}
