export const SESSION_LIFETIME_MS = 8 * 60 * 60 * 1000;

/** Use the original authentication time, never the refreshed token's issued-at time. */
export function sessionDeadline(accessToken: string): number {
  try {
    const payload = accessToken.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const claims = JSON.parse(atob(payload));
    const times = [claims.auth_time, ...(Array.isArray(claims.amr) ? claims.amr.map((entry: { timestamp?: unknown }) => entry?.timestamp) : [])]
      .filter((value): value is number => typeof value === "number" && Number.isFinite(value) && value > 0);
    return times.length ? Math.min(...times) * 1000 + SESSION_LIFETIME_MS : 0;
  } catch {
    return 0;
  }
}

export function sessionExpired(accessToken: string, now = Date.now()): boolean {
  return now >= sessionDeadline(accessToken);
}
