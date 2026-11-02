"use client";

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, ArrowUpRight, Eye, EyeOff } from "lucide-react";
import { Brand, Emblem } from "@/components/brand";
import { Reveal } from "@/components/reveal";
import { safeNext, supabase, supabaseConfigured } from "@/lib/supabase";

type Mode = "signin" | "signup" | "forgot" | "reset";

const copy: Record<Mode, { eyebrow: string; title: [string, string]; submit: string }> = {
  signin: { eyebrow: "WELCOME BACK.", title: ["Sign in to", "your thinking space."], submit: "Sign in" },
  signup: { eyebrow: "PULL UP A CHAIR.", title: ["Create your", "thinking space."], submit: "Create account" },
  forgot: { eyebrow: "IT HAPPENS.", title: ["Reset your", "password."], submit: "Send reset link" },
  reset: { eyebrow: "ALMOST THERE.", title: ["Choose a", "new password."], submit: "Save new password" },
};

const ORBITS = [0, 45, 90, 135];
// One loop around an orbit (rx 15, ry 35) before that orbit is rotated into place.
const ORBIT_PATH = "M40 5 a15 35 0 1 1 0 70 a15 35 0 1 1 0 -70";

/** The Sonia atom: orbits draw in, the atom turns slowly and electrons travel the orbits. */
function AnimatedAtom() {
  return (
    <svg className="art-atom" viewBox="0 0 80 80" fill="none" aria-hidden="true">
      <g className="art-atom-spin">
        {ORBITS.map((angle, index) => (
          <g key={angle} transform={`rotate(${angle} 40 40)`}>
            <ellipse cx="40" cy="40" rx="15" ry="35" stroke="currentColor" strokeWidth="1.5"
              pathLength={1} className="art-orbit" style={{ animationDelay: `${0.7 + index * 0.12}s` }} />
            <circle r="1.6" fill="currentColor" className="art-electron">
              <animateMotion dur={`${6 + index * 1.5}s`} begin={`${1.6 + index * 0.3}s`}
                repeatCount="indefinite" path={ORBIT_PATH} />
            </circle>
          </g>
        ))}
      </g>
      <circle cx="40" cy="40" r="5" fill="currentColor" className="art-nucleus" />
    </svg>
  );
}

export default function AuthPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [next, setNext] = useState("/chat");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const destination = safeNext(params.get("next"));
    setNext(destination);
    if (params.get("mode") === "signup") setMode("signup");

    // A password-reset email link signs the user in with a recovery session.
    const { data } = supabase.auth.onAuthStateChange((event) => {
      if (event === "PASSWORD_RECOVERY") setMode("reset");
    });
    supabase.auth.getSession().then(({ data: { session } }) => {
      const recovering = window.location.hash.includes("type=recovery");
      if (session && !recovering) router.replace(destination);
    });
    return () => data.subscription.unsubscribe();
  }, [router]);

  function switchMode(target: Mode) {
    setMode(target);
    setError("");
    setInfo("");
    setPassword("");
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setInfo("");
    try {
      if (mode === "signin") {
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) throw error;
        router.replace(next);
      } else if (mode === "signup") {
        const { data, error } = await supabase.auth.signUp({
          email, password,
          options: { emailRedirectTo: `${window.location.origin}/auth?next=${encodeURIComponent(next)}` },
        });
        if (error) throw error;
        if (data.session) router.replace(next);
        else {
          setInfo(`We sent a confirmation link to ${email}. Open it to finish creating your account.`);
          setPassword("");
        }
      } else if (mode === "forgot") {
        const { error } = await supabase.auth.resetPasswordForEmail(email, {
          redirectTo: `${window.location.origin}/auth`,
        });
        if (error) throw error;
        setInfo(`If an account exists for ${email}, a reset link is on its way.`);
      } else {
        const { error } = await supabase.auth.updateUser({ password });
        if (error) throw error;
        router.replace(next);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  const { eyebrow, title, submit: submitLabel } = copy[mode];
  const needsEmail = mode !== "reset";
  const needsPassword = mode !== "forgot";

  return (
    <main className="account-page">
      <section className="account-art account-art-animated">
        <span className="art-glow" aria-hidden />
        <Brand light />
        <div className="account-statement">
          <p className="eyebrow art-eyebrow">A FRESH PERSPECTIVE AWAITS.</p>
          <h1 aria-label="Your next good idea starts here.">
            {["Your next", "good idea"].map((line, index) => (
              <span key={line} className="art-line" aria-hidden>
                <span style={{ animationDelay: `${0.25 + index * 0.14}s` }}>{line}</span>
              </span>
            ))}
            <span className="art-line" aria-hidden>
              <em style={{ animationDelay: "0.53s" }}>starts here.</em>
            </span>
          </h1>
          <AnimatedAtom />
          <p className="art-tagline">
            <span>A thoughtful companion.</span>
            <span>A clearer way to read the room.</span>
          </p>
        </div>
        <span className="mono art-footer">SONIA — MADE FOR CURIOUS MINDS.</span>
      </section>
      <section className="account-content">
        <Link href="/" className="text-link">
          <ArrowLeft size={15} /> Back to Sonia
        </Link>
        <Reveal className="account-card">
          <Emblem />
          <p className="eyebrow">{eyebrow}</p>
          <h2>
            {title[0]}
            <br />
            <em>{title[1]}</em>
          </h2>

          {(mode === "signin" || mode === "signup") && (
            <div className="auth-tabs" role="tablist" aria-label="Account">
              <button type="button" role="tab" aria-selected={mode === "signin"} onClick={() => switchMode("signin")}>
                Sign in
              </button>
              <button type="button" role="tab" aria-selected={mode === "signup"} onClick={() => switchMode("signup")}>
                Create account
              </button>
            </div>
          )}

          {!supabaseConfigured && (
            <p className="auth-message auth-error" role="alert">
              Sign-in isn’t configured yet. Add NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY
              to .env.local and restart the dev server.
            </p>
          )}

          <form className="auth-form" onSubmit={submit}>
            {needsEmail && (
              <label>
                <span className="mono">EMAIL</span>
                <input type="email" name="email" autoComplete="email" required value={email}
                  onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com" />
              </label>
            )}
            {needsPassword && (
              <label>
                <span className="mono">{mode === "reset" ? "NEW PASSWORD" : "PASSWORD"}</span>
                <span className="auth-password">
                  <input type={showPassword ? "text" : "password"} name="password" required minLength={6}
                    autoComplete={mode === "signin" ? "current-password" : "new-password"}
                    value={password} onChange={(event) => setPassword(event.target.value)}
                    placeholder={mode === "signin" ? "Your password" : "At least 6 characters"} />
                  <button type="button" onClick={() => setShowPassword((shown) => !shown)}
                    aria-label={showPassword ? "Hide password" : "Show password"}>
                    {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </span>
              </label>
            )}

            {error && <p className="auth-message auth-error" role="alert">{error}</p>}
            {info && <p className="auth-message" role="status">{info}</p>}

            <button type="submit" className="button button-orange" disabled={busy || !supabaseConfigured}>
              {busy ? "One moment…" : submitLabel} <ArrowUpRight size={18} />
            </button>
          </form>

          <div className="auth-links">
            {mode === "signin" && (
              <button type="button" className="text-link" onClick={() => switchMode("forgot")}>
                Forgot your password?
              </button>
            )}
            {mode === "forgot" && (
              <button type="button" className="text-link" onClick={() => switchMode("signin")}>
                <ArrowLeft size={14} /> Back to sign in
              </button>
            )}
          </div>
        </Reveal>
        <span className="mono account-footer">LESS NOISE. MORE MEANING.</span>
      </section>
    </main>
  );
}
