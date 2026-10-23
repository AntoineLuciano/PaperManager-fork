import { useSyncExternalStore } from "react";

// Instance settings from the server's .env (GET /auth/instance, public): the accent
// colour and which fast model is set up. Loaded once at startup, before login.
export type InstanceInfo = {
  accent: string;
  fast_provider: "litellm" | "anthropic" | "openai" | null;
  fast_model: string;
  fast_model_label: string;
  anthropic: boolean;
  storage: "local" | "drive";
};

const ACCENT_PRESETS: Record<string, string> = {
  violet: "#7c3aed",
  blue: "#2563eb",
  teal: "#0d9488",
  green: "#16a34a",
  amber: "#d97706",
  rose: "#e11d48",
  slate: "#475569",
};

// Share of the accent in each shade, mixed with white below 600 and black above.
// The app is styled with Tailwind's violet scale, so the accent replaces that scale.
const SHADES: Array<[number, number, "white" | "black"]> = [
  [50, 8, "white"], [100, 15, "white"], [200, 30, "white"], [300, 50, "white"],
  [400, 75, "white"], [500, 88, "white"], [600, 100, "white"], [700, 82, "black"],
  [800, 66, "black"], [900, 52, "black"], [950, 36, "black"],
];

let info: InstanceInfo | null = null;
const listeners = new Set<() => void>();

export function applyAccent(accent: string) {
  const value = (ACCENT_PRESETS[accent.trim().toLowerCase()] ?? accent).trim();
  if (!/^#[0-9a-f]{6}$/i.test(value) || value.toLowerCase() === ACCENT_PRESETS.violet) return;
  const style = document.documentElement.style;
  for (const [shade, pct, other] of SHADES) {
    style.setProperty(`--color-violet-${shade}`, `color-mix(in oklab, ${value} ${pct}%, ${other})`);
  }
  style.setProperty("--color-accent", value);
  style.setProperty("--color-accent-lo", "var(--color-violet-50)");
  style.setProperty("--color-accent-border", "var(--color-violet-200)");
}

export async function loadInstance() {
  try {
    const res = await fetch(`${import.meta.env.VITE_API_URL ?? "http://localhost:8000"}/auth/instance`);
    if (!res.ok) return;
    info = await res.json();
    applyAccent(info!.accent);
    listeners.forEach((l) => l());
  } catch {
    // Older backend or offline: keep the default look and labels.
  }
}

export function instanceInfo(): InstanceInfo | null {
  return info;
}

export function useInstance(): InstanceInfo | null {
  return useSyncExternalStore(
    (l) => { listeners.add(l); return () => listeners.delete(l); },
    () => info,
  );
}

/** Display name of the fast ("litellm") model option, e.g. "Claude Haiku 4.5" or "GPT-5 mini". */
export function fastModelLabel(): string {
  return info?.fast_model_label || "Fast model";
}
