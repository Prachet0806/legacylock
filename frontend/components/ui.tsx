"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Copy, Loader2, X } from "lucide-react";
import { clsx } from "clsx";

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={clsx("h-4 w-4 animate-spin", className)} aria-label="Loading" />;
}

export function StatusChip({
  tone,
  children,
  pulse,
}: {
  tone: "success" | "warn" | "danger" | "neutral";
  children: React.ReactNode;
  pulse?: boolean;
}) {
  const dot =
    tone === "success"
      ? "bg-success"
      : tone === "warn"
        ? "bg-warn"
        : tone === "danger"
          ? "bg-danger"
          : "bg-faint";
  return (
    <span className="chip">
      <span className={clsx("h-2 w-2 rounded-full", dot, pulse && "motion-safe:animate-pulse")} />
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
    <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border px-6 py-10 text-center">
      <div className="text-faint">{icon}</div>
      <p className="font-medium">{title}</p>
      <p className="max-w-sm text-sm text-muted">{hint}</p>
      {action}
    </div>
  );
}

export function CopyButton({ text, label }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="btn-ghost px-2 py-1 text-xs"
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
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={() => dismissable && onClose()}
    >
      <div
        className={clsx("card w-full", wide ? "max-w-2xl" : "max-w-md")}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button ref={closeRef} type="button" className="btn-ghost px-2 py-1" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
