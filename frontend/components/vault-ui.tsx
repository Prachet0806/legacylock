"use client";

import { clsx } from "clsx";

export type VaultState = "active" | "grace" | "triggered";

const STATES: VaultState[] = ["active", "grace", "triggered"];
const LABELS: Record<VaultState, string> = { active: "Active", grace: "Grace", release: "Release" } as unknown as Record<VaultState, string>;

export function stateTone(s: VaultState | string | null): "success" | "warn" | "danger" | "neutral" {
  if (s === "triggered") return "danger";
  if (s === "grace") return "warn";
  if (s === "active") return "success";
  return "neutral";
}

export function StateTimeline({ state }: { state: VaultState | string | null }) {
  const idx = state ? STATES.indexOf(state as VaultState) : -1;
  const labels = ["Active", "Grace", "Release"];
  return (
    <ol className="flex items-center" aria-label="Vault release timeline">
      {STATES.map((s, i) => (
        <li key={s} className="flex flex-1 items-center last:flex-none">
          <div className="flex flex-col items-center gap-1.5">
            <span
              className={clsx(
                "flex h-8 w-8 items-center justify-center rounded-full text-xs font-bold transition-colors",
                i < idx && "bg-success text-black",
                i === idx && s === "active" && "bg-success text-black",
                i === idx && s === "grace" && "motion-safe:animate-pulse bg-warn text-black",
                i === idx && s === "triggered" && "bg-danger text-white",
                (i > idx || idx === -1) && "border border-border bg-raised text-muted",
              )}
              aria-current={i === idx ? "step" : undefined}
            >
              {i + 1}
            </span>
            <span className={clsx("text-xs", i === idx ? "font-medium text-text" : "text-faint")}>{labels[i]}</span>
          </div>
          {i < STATES.length - 1 && (
            <div className={clsx("mx-3 h-0.5 flex-1 rounded-full", i < idx ? "bg-success" : "bg-border")} aria-hidden="true" />
          )}
        </li>
      ))}
    </ol>
  );
}

export function formatCountdown(target: string | null, now = Date.now()): string {
  if (!target) return "—";
  const ms = new Date(target).getTime() - now;
  if (ms <= 0) return "due now";
  const d = Math.floor(ms / 86400000);
  const h = Math.floor((ms % 86400000) / 3600000);
  const m = Math.floor((ms % 3600000) / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  if (d > 0) return `${d}d ${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export function RecoveryReadiness({ assigned, threshold, total }: { assigned: number; threshold: number; total: number }) {
  const ready = assigned >= threshold;
  const pct = Math.min(100, (assigned / Math.max(1, total)) * 100);
  const dots = Array.from({ length: total }, (_, i) => i < assigned);
  return (
    <div className="surface-lg">
      <div className="flex items-center justify-between gap-3">
          <h2 className="font-semibold">Accepted share assignments</h2>
        <span className={clsx("text-xs font-medium", ready ? "text-success" : "text-warn")}>
            {ready ? "Quorum assigned" : "Quorum incomplete"}
        </span>
      </div>
      <div className="mt-3 flex items-center gap-1.5" aria-hidden="true">
        {dots.map((filled, i) => (
          <span key={i} className={clsx("h-2.5 w-2.5 rounded-full", filled ? "bg-success" : "bg-raised")} />
        ))}
      </div>
      <p className="mt-3 text-sm text-muted">
          {assigned} of {total} current shares assigned to accepted recipients · {threshold} required
      </p>
      <progress className={clsx("progress-track mt-2", ready ? "progress-success" : "progress-warn")} value={pct} max={100} aria-label="Accepted share assignments" />
      {!ready && (
        <p className="mt-3 text-sm text-warn">
            Enroll and assign {threshold - assigned} more {threshold - assigned === 1 ? "trusted person" : "trusted people"}. Assignment metadata does not prove share possession.
        </p>
      )}
    </div>
  );
}

export { LABELS };
