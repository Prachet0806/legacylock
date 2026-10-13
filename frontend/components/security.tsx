"use client";

import { useState } from "react";
import { Info, Lock, LockOpen, ShieldCheck } from "lucide-react";
import { clsx } from "clsx";

export function VaultLockIndicator({ unlocked, onLock }: { unlocked: boolean; onLock?: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={clsx(
          "chip !py-1 transition-colors hover:border-faint",
          unlocked ? "text-warn" : "text-success",
        )}
        aria-expanded={open}
        aria-label={unlocked ? "Vault unlocked — view security" : "Vault protected — view security"}
      >
        <span className={clsx("vault-dot", unlocked ? "bg-warn" : "bg-success")} />
        {unlocked ? "Vault unlocked" : "Vault protected"}
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} aria-hidden="true" />
          <div className="absolute right-0 z-50 mt-2 w-72 rounded-2xl border border-border bg-surface p-4 shadow-vault">
            <p className="mb-3 text-sm font-semibold">Vault security</p>
            <ul className="flex flex-col gap-2 text-sm">
              <li className="flex items-center gap-2 text-muted">
                {unlocked ? <LockOpen className="h-3.5 w-3.5 text-warn" /> : <Lock className="h-3.5 w-3.5 text-success" />}
                {unlocked ? "Vault unlocked in this tab" : "Vault locked"}
              </li>
              <li className="flex items-center gap-2 text-muted">
                <ShieldCheck className="h-3.5 w-3.5 text-success" />
                Local encryption enabled
              </li>
              <li className="flex items-center gap-2 text-muted">
                <ShieldCheck className="h-3.5 w-3.5 text-success" />
                Recovery configured
              </li>
              <li className="flex items-center gap-2 text-muted">
                <ShieldCheck className="h-3.5 w-3.5 text-success" />
                Heartbeat active
              </li>
            </ul>
            <p className="mt-3 text-xs leading-relaxed text-faint">
              {unlocked ? "Your vault is open in this tab. It locks when the tab closes." : "Your vault is currently protected."}
            </p>
            {unlocked && onLock && (
              <button type="button" className="btn-ghost mt-3 w-full text-xs" onClick={() => { onLock(); setOpen(false); }}>
                Lock vault now
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}

export function EncryptionNotice({ compact = false }: { compact?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={compact ? "" : "rounded-xl bg-raised/50 px-3 py-2"}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-xs text-muted hover:text-text"
        aria-expanded={open}
      >
        <Lock className="h-3.5 w-3.5 text-success" />
        Encrypted locally
        <Info className="h-3.5 w-3.5 text-faint" />
      </button>
      {open && (
        <div className="mt-2 text-xs leading-relaxed text-muted">
          <p className="font-medium text-text">Why is this private?</p>
          <p className="mt-1">Your message is encrypted in this browser before LegacyLock receives it.</p>
          <p className="mt-1">LegacyLock never receives:</p>
          <ul className="mt-1 list-disc pl-4">
            <li>your message</li>
            <li>your vault passphrase</li>
            <li>your vault key</li>
            <li>your recovery shares</li>
          </ul>
        </div>
      )}
    </div>
  );
}

export function SecurityChecklist({ items }: { items: { label: string; ok: boolean }[] }) {
  return (
    <ul className="flex flex-col gap-2.5">
      {items.map((i) => (
        <li key={i.label} className="flex items-center gap-2.5 text-sm">
          <span
            className={clsx(
              "flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-bold",
              i.ok ? "bg-success/15 text-success" : "bg-raised text-faint",
            )}
            aria-hidden="true"
          >
            {i.ok ? "✓" : "○"}
          </span>
          <span className={i.ok ? "text-text" : "text-muted"}>{i.label}</span>
        </li>
      ))}
    </ul>
  );
}
