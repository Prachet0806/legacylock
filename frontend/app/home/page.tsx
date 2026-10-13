"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, CheckCircle2, Vault as VaultIcon } from "lucide-react";
import { checkin, getHeartbeat, getRecoveryPolicy, getStats, getVaultStatus, nextDeadline } from "../../lib/client";
import { useToast } from "../../components/toast";
import { SecurityChecklist } from "../../components/security";
import { formatCountdown, stateTone } from "../../components/vault-ui";
import { StatusChip } from "../../components/ui";

function greeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

export default function Dashboard() {
  const { notify } = useToast();
  const [status, setStatus] = useState<string | null>(null);
  const [counts, setCounts] = useState<{ messages: number; beneficiaries: number } | null>(null);
  const [deadline, setDeadline] = useState<string | null>(null);
  const [lastCheckin, setLastCheckin] = useState<string | null>(null);
  const [recovery, setRecovery] = useState<{ threshold: number; total: number; assigned: number } | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    (async () => {
      let beneficiaryCount = 0;
      try {
        const s = await getStats();
        setStatus(s.vault_status);
        setCounts({ messages: s.message_count, beneficiaries: s.beneficiary_count });
        beneficiaryCount = s.beneficiary_count;
      } catch {
        /* logged out — landing content still renders */
      }
      try {
        const hb = await getHeartbeat();
        setDeadline(nextDeadline(hb));
        setLastCheckin(hb.last_check_in ?? null);
      } catch {
        /* heartbeat may not exist yet */
      }
      try {
        const policy = await getRecoveryPolicy().catch(() => null);
        if (policy) setRecovery({ threshold: policy.recovery_threshold, total: policy.recovery_total, assigned: beneficiaryCount });
      } catch {
        /* ignore */
      }
    })();
  }, []);

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  async function onCheckin() {
    try {
      await checkin();
      const [hb, vs] = await Promise.all([getHeartbeat(), getVaultStatus()]);
      setDeadline(nextDeadline(hb));
      setLastCheckin(hb.last_check_in ?? null);
      setStatus(vs.status);
      notify("success", "Checked in — deadline extended.");
    } catch {
      notify("error", "Check-in failed. Are you logged in?");
    }
  }

  const tone = stateTone(status);
  const heroLabel = status === "triggered" ? "RELEASED" : status === "grace" ? "GRACE PERIOD" : "ACTIVE";

  return (
    <main className="mx-auto max-w-5xl px-4 py-8 sm:py-10">
      <p className="text-sm text-muted">{greeting()}</p>
      <h1 className="page-title mt-1 text-balance">Your legacy is protected.</h1>

      {/* Hero — heartbeat countdown is the product's heartbeat */}
      <section className="surface-hero mt-6" aria-label="Vault status">
        <StatusChip tone={tone} pulse={status === "grace"} className="mx-auto">
          <span aria-live="polite">● {heroLabel}</span>
        </StatusChip>
        <p className="eyebrow mt-6">Next check-in</p>
        <p className="mt-2 font-mono text-4xl font-bold tabular-nums tracking-tight sm:text-5xl" aria-live="off">
          {formatCountdown(deadline, now)}
        </p>
        <p className="supporting mt-2">until check-in</p>
        <button type="button" className="btn-primary mt-6 min-w-44" onClick={onCheckin}>
          <CheckCircle2 className="h-4 w-4" />
          Check in
        </button>
        <p className="mt-4 text-xs text-faint">
          Last check-in: {lastCheckin ? new Date(lastCheckin).toLocaleString() : "never"}
        </p>
      </section>

      {/* Stat tiles */}
      <section className="mt-4 grid gap-3 sm:grid-cols-3" aria-label="Vault summary">
        <Link href="/vault" className="stat-tile transition-colors hover:border-faint">
          <span className="text-3xl font-bold tabular-nums">{counts?.messages ?? "–"}</span>
          <span className="text-sm text-muted">Private notes</span>
        </Link>
        <Link href="/beneficiaries" className="stat-tile transition-colors hover:border-faint">
          <span className="text-3xl font-bold tabular-nums">{counts?.beneficiaries ?? "–"}</span>
          <span className="text-sm text-muted">Trusted people</span>
        </Link>
        <Link href="/beneficiaries" className="stat-tile transition-colors hover:border-faint">
          <span className="text-3xl font-bold tabular-nums">
            {recovery ? `${recovery.assigned} / ${recovery.total}` : counts != null ? `${counts.beneficiaries} / 3` : "–"}
          </span>
          <span className="text-sm text-muted">Recovery shares</span>
        </Link>
      </section>

      {/* Protection checklist — human layer only */}
      <section className="surface-lg mt-4">
        <div className="flex items-center gap-2">
          <VaultIcon className="h-4 w-4 text-accent" />
          <h2 className="font-semibold">Your protection</h2>
        </div>
        <div className="mt-4">
          <SecurityChecklist
            items={[
              { label: "Messages encrypted locally", ok: true },
              { label: "Recovery configured", ok: (counts?.beneficiaries ?? 0) > 0 },
              {
                label: counts ? `${counts.beneficiaries} ${counts.beneficiaries === 1 ? "trusted person" : "trusted people"} assigned` : "Trusted people assigned",
                ok: (counts?.beneficiaries ?? 0) > 0,
              },
              { label: "Heartbeat active", ok: status === "active" || status === "grace" },
            ]}
          />
        </div>
        <Link href="/settings/security" className="mt-4 inline-flex items-center gap-1 text-sm text-muted hover:text-text">
          How your privacy works
          <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </section>
    </main>
  );
}
