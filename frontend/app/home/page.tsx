"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ArrowRight,
  HeartPulse,
  KeyRound,
  ShieldCheck,
  Timer,
  Users,
  Vault as VaultIcon,
} from "lucide-react";
import { getStats } from "../../lib/client";
import { StatusChip } from "../../components/ui";

const STEPS = [
  {
    icon: KeyRound,
    title: "Encrypt",
    hint: "Messages are encrypted in your browser with AES-256-GCM. The server only ever sees ciphertext.",
  },
  {
    icon: Timer,
    title: "Check in",
    hint: "Confirm you're around on your own schedule. Missed check-ins move the vault toward release.",
  },
  {
    icon: HeartPulse,
    title: "Release",
    hint: "After the grace period, the vault transitions to TRIGGERED — automatically and idempotently.",
  },
  {
    icon: Users,
    title: "Recover",
    hint: "Beneficiaries combine k-of-n Shamir shares to reconstruct the key and decrypt — locally.",
  },
];

export default function Dashboard() {
  const [status, setStatus] = useState<string | null>(null);
  const [counts, setCounts] = useState<{ messages: number; beneficiaries: number } | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const s = await getStats();
        setStatus(s.vault_status);
        setCounts({ messages: s.message_count, beneficiaries: s.beneficiary_count });
      } catch {
        /* logged out — landing content still renders */
      }
    })();
  }, []);

  return (
    <main className="mx-auto max-w-5xl px-4 py-10">
      {/* Hero */}
      <section className="flex flex-col items-start gap-4 py-8">
        <div className="flex items-center gap-2">
          <VaultIcon className="h-8 w-8 text-accent" />
          {status && (
            <StatusChip tone={status === "triggered" ? "danger" : status === "grace" ? "warn" : "success"}>
              {status.toUpperCase()}
            </StatusChip>
          )}
        </div>
        <h1 className="max-w-2xl text-4xl font-bold leading-tight">
          Your legacy, sealed with <span className="text-accent">zero knowledge</span>.
        </h1>
        <p className="max-w-xl text-muted">
          LegacyLock stores your sensitive messages encrypted and releases them to your
          beneficiaries only after prolonged inactivity. The server can never read your data —
          not your messages, not your keys, not your shares.
        </p>
        <div className="flex gap-3">
          <Link href="/vault/setup" className="btn-primary">
            Set up your vault
            <ArrowRight className="h-4 w-4" />
          </Link>
          <Link href="/vault" className="btn-ghost">
            Open vault
          </Link>
        </div>
        {counts && (
          <div className="mt-2 flex gap-2">
            <span className="chip">{counts.messages} messages</span>
            <span className="chip">{counts.beneficiaries} beneficiaries</span>
          </div>
        )}
      </section>

      {/* How it works */}
      <section className="grid gap-4 py-8 sm:grid-cols-2 lg:grid-cols-4">
        {STEPS.map((s, i) => {
          const Icon = s.icon;
          return (
            <div key={s.title} className="card flex flex-col gap-2">
              <div className="flex items-center gap-2">
                <span className="flex h-8 w-8 items-center justify-center rounded-md bg-raised">
                  <Icon className="h-4 w-4 text-accent" />
                </span>
                <span className="text-xs text-faint">Step {i + 1}</span>
              </div>
              <h2 className="font-semibold">{s.title}</h2>
              <p className="text-sm text-muted">{s.hint}</p>
            </div>
          );
        })}
      </section>

      {/* Security strip */}
      <section className="card flex flex-col gap-3 sm:flex-row sm:items-center">
        <ShieldCheck className="h-8 w-8 shrink-0 text-success" />
        <div>
          <h2 className="font-semibold">Server-blind by design</h2>
          <p className="text-sm text-muted">
            AES-256-GCM message encryption, PBKDF2 key wrapping, and Shamir threshold recovery —
            all computed in your browser via WebCrypto. Plaintext, passphrases, and raw shares
            are never transmitted or logged.
          </p>
        </div>
      </section>
    </main>
  );
}
