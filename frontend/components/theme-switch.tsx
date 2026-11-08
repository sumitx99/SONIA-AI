"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { ThemeProvider, useTheme } from "next-themes";
import { Monitor, Moon, Sun } from "lucide-react";

export function SoniaTheme({ children }: { children: ReactNode }) {
  return <ThemeProvider attribute={["class", "data-theme"]} storageKey="sonia-appearance" defaultTheme="light" enableSystem themes={["light", "dark"]}><AppearanceProvider>{children}</AppearanceProvider></ThemeProvider>;
}

const choices = [
  { value: "system", label: "System", description: "Follow your device’s appearance.", icon: Monitor },
  { value: "light", label: "Light", description: "Warm paper. A fresh perspective.", icon: Sun },
  { value: "dark", label: "Dark", description: "Deep ink. Room to focus.", icon: Moon },
];

export function ThemeSwitch({ expanded = false }: { expanded?: boolean }) {
  const { theme, resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
    if (theme && theme !== "light" && theme !== "dark" && theme !== "system") setTheme("light");
  }, [theme, setTheme]);

  return <div className={`theme-switch${expanded ? " theme-switch-expanded" : ""}`} role="group" aria-label="Appearance">
    {choices.filter(choice => expanded || choice.value !== "system").map(({ value, label, description, icon: Icon }) => <button key={value} type="button"
      aria-label={`${label} appearance`} title={label} aria-pressed={mounted && (expanded ? theme : resolvedTheme) === value}
      onClick={() => setTheme(value)}>
      <span className={`theme-swatch theme-swatch-${value}`}><Icon size={18} aria-hidden="true" /></span>
      {expanded && <span><strong>{label}</strong><small>{description}</small></span>}
    </button>)}
  </div>;
}


type Mode = "light" | "dark";
type Palette = { accent: string; background: string; foreground: string; preset: string };
type Appearance = { separate: boolean; palettes: Record<Mode, Palette | null>; uiSize: number; codeSize: number; contrast: number };
const defaults: Appearance = { separate: true, palettes: { light: null, dark: null }, uiSize: 14, codeSize: 12, contrast: 50 };
const basePalettes: Record<Mode, Palette> = {
  light: { preset: "sonia", accent: "#df3d33", background: "#f7f7f5", foreground: "#222222" },
  dark: { preset: "sonia", accent: "#f18b72", background: "#10171e", foreground: "#e6ecef" },
};
const presets = [
  { id: "sonia", name: "Sonia original" },
  { id: "ocean", name: "Ocean" },
  { id: "forest", name: "Forest" },
];
const preferenceKey = "sonia-display-preferences";
const hex = /^#[0-9a-f]{6}$/i;
const AppearanceContext = createContext<{ value: Appearance; update: (next: Appearance) => void; saved: boolean } | null>(null);
function channel(color: string) { return [1, 3, 5].map(i => parseInt(color.slice(i, i + 2), 16)); }
function mix(a: string, b: string, amount: number) {
  const end = channel(b);
  return "#" + channel(a).map((c, i) => Math.round(c * (1 - amount) + end[i] * amount).toString(16).padStart(2, "0")).join("");
}
function luminance(color: string) {
  return channel(color).map(v => { const n = v / 255; return n <= .04045 ? n / 12.92 : ((n + .055) / 1.055) ** 2.4; }).reduce((sum, n, i) => sum + n * [.2126, .7152, .0722][i], 0);
}
function ratio(a: string, b: string) { const x = luminance(a), y = luminance(b); return (Math.max(x,y) + .05) / (Math.min(x,y) + .05); }
function readable(color: string, background: string) {
  if (ratio(color, background) >= 4.5) return color;
  const target = ratio("#ffffff", background) > ratio("#111111", background) ? "#ffffff" : "#111111";
  for (let n = .1; n <= 1; n += .1) { const result = mix(color, target, n); if (ratio(result, background) >= 4.5) return result; }
  return target;
}
function parsePreferences(raw: string | null): Appearance {
  try {
    const data = JSON.parse(raw || "null");
    if (!data || typeof data !== "object") return defaults;
    const palette = (value: unknown): Palette | null => {
      if (!value || typeof value !== "object") return null;
      const p = value as Palette;
      return [p.accent, p.background, p.foreground].every(v => typeof v === "string" && hex.test(v))
        ? { accent: p.accent, background: p.background, foreground: readable(p.foreground, p.background), preset: presets.some(x => x.id === p.preset) ? p.preset : "custom" } : null;
    };
    const bounded = (value: unknown, min: number, max: number, fallback: number) => typeof value === "number" && Number.isFinite(value) ? Math.max(min, Math.min(max, value)) : fallback;
    return { separate: data.separate !== false, palettes: { light: palette(data.palettes?.light), dark: palette(data.palettes?.dark) }, uiSize: bounded(data.uiSize,12,20,14), codeSize: bounded(data.codeSize,10,20,12), contrast: bounded(data.contrast,0,100,50) };
  } catch { return defaults; }
}
function AppearanceProvider({ children }: { children: ReactNode }) {
  const { resolvedTheme } = useTheme();
  const [value, setValue] = useState<Appearance>(defaults);
  const [saved, setSaved] = useState(true);
  useEffect(() => {
    try { setValue(parsePreferences(localStorage.getItem(preferenceKey))); } catch { setSaved(false); }
    const receive = (event: StorageEvent) => { if (event.key === preferenceKey || event.key === null) setValue(parsePreferences(event.newValue)); };
    window.addEventListener("storage", receive);
    return () => window.removeEventListener("storage", receive);
  }, []);
  function update(next: Appearance) {
    setValue(next);
    try { localStorage.setItem(preferenceKey, JSON.stringify(next)); setSaved(true); } catch { setSaved(false); }
  }
  useEffect(() => {
    const root = document.documentElement;
    const mode: Mode = resolvedTheme === "dark" ? "dark" : "light";
    const palette = value.palettes[mode];
    const owned: string[] = [];
    const set = (key: string, val: string) => { root.style.setProperty(key, val); owned.push(key); };
    set("--appearance-ui-size", `${value.uiSize}px`);
    set("--appearance-code-size", `${value.codeSize}px`);
    root.dataset.appearanceCustom = palette || value.contrast !== 50 ? "true" : "false";
    if (palette || value.contrast !== 50) {
      const p = palette || basePalettes[mode];
      const foreground = readable(p.foreground, p.background);
      const card = mix(p.background, foreground, .035);
      const muted = readable(mix(p.background, foreground, .48 + value.contrast / 250), p.background);
      for (const key of ["--paper", "--background"]) set(key, p.background);
      for (const key of ["--ink", "--foreground", "--card-foreground", "--popover-foreground"]) set(key, foreground);
      for (const key of ["--card", "--popover"]) set(key, card);
      for (const key of ["--line", "--border", "--input"]) set(key, mix(p.background, foreground, .14 + value.contrast / 1000));
      for (const key of ["--primary", "--ring", "--orange", "--citron"]) set(key, p.accent);
      set("--primary-foreground", readable("#ffffff", p.accent));
      set("--appearance-link", readable(p.accent, p.background));
      set("--muted-foreground", muted);
      set("--surface-tint", mix(p.background, foreground, .07));
      set("--user-bubble", mix(p.background, p.accent, .1));
      set("--header-glass", p.background + "ed");
    }
    return () => { owned.forEach(key => root.style.removeProperty(key)); delete root.dataset.appearanceCustom; };
  }, [value, resolvedTheme]);
  return <AppearanceContext.Provider value={{ value, update, saved }}>{children}</AppearanceContext.Provider>;
}

export function AppearanceSettings() {
  const preferences = useContext(AppearanceContext);
  const { resolvedTheme } = useTheme();
  if (!preferences) return null;
  const { value, update, saved } = preferences;
  const mode: Mode = resolvedTheme === "dark" ? "dark" : "light";
  const current = value.palettes[mode] || basePalettes[mode];
  function changePalette(next: Palette | null) {
    update({ ...value, palettes: value.separate ? { ...value.palettes, [mode]: next } : { light: next, dark: next } });
  }
  function choosePreset(id: string) {
    if (id === "sonia") { changePalette(null); return; }
    const dark = mode === "dark";
    changePalette({ preset: id, accent: id === "ocean" ? (dark ? "#7fb9ec" : "#28628c") : (dark ? "#9ac9ab" : "#36704f"), background: id === "ocean" ? (dark ? "#101e2c" : "#f1f6fa") : (dark ? "#13221e" : "#f3f5ee"), foreground: dark ? "#e9efed" : "#24332d" });
  }
  return <section className="appearance-settings" aria-label="Customize appearance">
    <div className="appearance-intro"><h3>Look &amp; feel</h3><span>APPEARANCE</span></div>
    <div className="appearance-mode"><ThemeSwitch expanded /></div>
    <div className="appearance-palette">
      <label className="appearance-row"><span>Palette<small>Start with a palette, then fine-tune.</small></span><select aria-label="Theme preset" value={current.preset} onChange={e => choosePreset(e.target.value)}>{presets.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}{current.preset === "custom" && <option value="custom">Custom</option>}</select></label>
      <div className="appearance-colours">{(["accent", "background", "foreground"] as const).map(key => <label className="appearance-colour-option" key={key}><span>{key === "foreground" ? "Text colour" : key[0].toUpperCase() + key.slice(1)}</span><span className="appearance-colour"><input type="color" aria-label={`${key} colour`} value={current[key]} onChange={e => { const next = { ...current, preset: "custom", [key]: e.target.value }; next.foreground = readable(next.foreground, next.background); changePalette(next); }} /><code>{current[key].toUpperCase()}</code></span></label>)}</div>
    </div>
    <p className="appearance-note">Changes apply instantly and are saved on this browser. Text colours adjust when needed to stay readable.</p>
    <details className="appearance-advanced"><summary>Advanced</summary><div className="appearance-group">
      <label className="appearance-row"><span>UI font size<small>Reading text and workspace controls.</small></span><span className="appearance-number"><input aria-label="UI font size" type="number" min={12} max={20} value={value.uiSize} onChange={e => { const n = e.target.valueAsNumber; if (Number.isFinite(n)) update({ ...value, uiSize: Math.max(12, Math.min(20, n)) }); }} />px</span></label>
      <label className="appearance-row"><span>Code font size<small>Code blocks in your conversations.</small></span><span className="appearance-number"><input aria-label="Code font size" type="number" min={10} max={20} value={value.codeSize} onChange={e => { const n = e.target.valueAsNumber; if (Number.isFinite(n)) update({ ...value, codeSize: Math.max(10, Math.min(20, n)) }); }} />px</span></label>
      <label className="appearance-row"><span>Separate light and dark colours<small>Keep an independent palette for each mode.</small></span><input type="checkbox" role="switch" checked={value.separate} onChange={e => update({ ...value, separate: e.target.checked, palettes: e.target.checked ? value.palettes : { light: value.palettes[mode], dark: value.palettes[mode] } })} /></label>
      <label className="appearance-row"><span>Contrast<small>Adjust secondary text and border definition.</small></span><span className="appearance-range"><input type="range" aria-label="Appearance contrast" min={0} max={100} value={value.contrast} onChange={e => update({ ...value, contrast: Number(e.target.value) })} /><output>{value.contrast}</output></span></label>
    </div></details>
    <button type="button" className="appearance-reset" onClick={() => update(defaults)}>Reset appearance</button>
    {!saved && <p role="status" className="appearance-note">Applied for this visit. Browser storage is unavailable, so these changes could not be saved.</p>}
  </section>;
}
