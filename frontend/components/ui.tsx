"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Copy, Loader2, X } from "lucide-react";
import { clsx } from "clsx";

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={clsx("h-4 w-4 animate-spin", className)} aria-label="Loading" />;
}

export type Tone = "success" | "warn" | "danger" | "neutral" | "brand";

const DOT: Record<Tone, string> = {
  success: "bg-success",
  warn: "bg-warn",
  danger: "bg-danger",
  neutral: "bg-faint",
  brand: "bg-accent",
};

export function StatusChip({
  tone,
  children,
  pulse,
  className,
}: {
  tone: Tone;
  children: React.ReactNode;
  pulse?: boolean;
  className?: string;
}) {
  return (
    <span className={clsx("chip", className)}>
      <span className={clsx("h-2 w-2 rounded-full", DOT[tone], pulse && "motion-safe:animate-pulse")} />
      {children}
    </span>
  );
}

export function Badge({
  tone = "neutral",
  children,
  className,
}: {
  tone?: Tone;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium",
        tone === "success" && "bg-success/15 text-success",
        tone === "warn" && "bg-warn/15 text-warn",
        tone === "danger" && "bg-danger/15 text-danger",
        tone === "brand" && "bg-accent/15 text-accent",
        tone === "neutral" && "bg-raised text-muted",
        className,
      )}
    >
      {children}
    </span>
  );
}

export function EmptyState({
  icon,
  title,
  hint,
  action,
}: {
  icon: React.ReactNode;
  title: string;
  hint: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-2xl border border-dashed border-border px-6 py-12 text-center">
      <div className="mb-1 flex h-11 w-11 items-center justify-center rounded-2xl bg-raised text-faint">{icon}</div>
      <p className="font-medium">{title}</p>
      <p className="max-w-sm text-sm leading-relaxed text-muted">{hint}</p>
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function CopyButton({ text, label }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="btn-ghost px-2.5 py-1.5 text-xs"
      title={label ?? "Copy"}
      aria-label={label ?? "Copy to clipboard"}
      onClick={async () => {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
    >
      {copied ? <Check className="h-3.5 w-3.5 text-success" /> : <Copy className="h-3.5 w-3.5" />}
      <span aria-live="polite">{copied ? "Copied" : (label ?? "Copy")}</span>
    </button>
  );
}

export function Modal({
  title,
  onClose,
  children,
  wide,
  dismissable = true,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  wide?: boolean;
  /** Share-ceremony style modals pass dismissable={false} to prevent accidents. */
  dismissable?: boolean;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && dismissable) onClose();
      // Minimal focus trap: wrap Tab around focusable elements in the dialog.
      if (e.key === "Tab") {
        const root = document.activeElement?.closest('[role="dialog"]');
        if (!root) return;
        const items = [...root.querySelectorAll<HTMLElement>(
           'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        )].filter((el) => !el.hasAttribute("disabled"));
        if (items.length === 0) return;
        const first = items[0];
        const last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose, dismissable]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-[2px]"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={() => dismissable && onClose()}
    >
      <div
        className={clsx("card w-full !rounded-2xl", wide ? "max-w-2xl" : "max-w-md")}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
          <button ref={closeRef} type="button" className="btn-ghost !rounded-xl px-2 py-1" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Avatar({ name, className }: { name: string; className?: string }) {
  return (
    <span
      className={clsx(
        "flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-raised text-sm font-semibold text-accent",
        className,
      )}
      aria-hidden="true"
    >
      {name.slice(0, 1).toUpperCase()}
    </span>
  );
}

export function ProgressBar({ value, max = 100, tone = "success", className }: { value: number; max?: number; tone?: Tone; className?: string }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <progress className={clsx("progress-track", `progress-${tone}`, className)} value={pct} max={100} />
  );
}

export function Stepper({ steps, current }: { steps: string[]; current: number }) {
  return (
    <ol className="flex items-center gap-2 text-sm" aria-label="Progress">
      {steps.map((label, i) => (
        <li key={label} className="flex items-center gap-2" aria-current={current === i + 1 ? "step" : undefined}>
          <span
            className={clsx(
              "flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold transition-colors",
              current > i + 1 ? "bg-success text-black" : current === i + 1 ? "bg-accent text-black" : "bg-raised text-muted",
            )}
          >
            {i + 1}
          </span>
          <span className={current === i + 1 ? "font-medium text-text" : "text-muted"}>{label}</span>
          {i < steps.length - 1 && <span className="mx-1 text-faint">—</span>}
        </li>
      ))}
    </ol>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("animate-pulse rounded-xl bg-raised", className)} aria-hidden="true" />;
}

export function SectionHeader({ title, hint, action }: { title: string; hint?: string; action?: React.ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h2 className="section-title">{title}</h2>
        {hint && <p className="supporting mt-1">{hint}</p>}
      </div>
      {action}
    </div>
  );
}
