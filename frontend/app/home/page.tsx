"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, CheckCircle2, Vault as VaultIcon } from "lucide-react";
import { checkin, getHeartbeat, getStats, getVaultStatus, nextDeadline } from "../../lib/client";
import { getReadiness, type Readiness } from "../../lib/api/owner";
import { useToast } from "../../components/toast";
import { SecurityChecklist } from "../../components/security";
import { formatCountdown, stateTone } from "../../components/vault-ui";
import { StatusChip } from "../../components/ui";

export default function Dashboard() {
  const { notify } = useToast();
  const [status, setStatus] = useState<string | null>(null);
  const [counts, setCounts] = useState<{ messages: number; beneficiaries: number } | null>(null);
  const [deadline, setDeadline] = useState<string | null>(null);
  const [lastCheckin, setLastCheckin] = useState<string | null>(null);
  const [recovery, setRecovery] = useState<Readiness | null>(null);
  const [heartbeatArmed, setHeartbeatArmed] = useState<boolean | null>(null);
  const [checkinError, setCheckinError] = useState("");
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    let cancelled = false;
    getStats().then((s) => {
      if (cancelled) return;
      setStatus(s.vault_status);
      setCounts({ messages: s.message_count, beneficiaries: s.beneficiary_count });
    }).catch(() => { /* logged out — landing content still renders */ });
    getHeartbeat().then((hb) => {
      if (cancelled) return;
      setDeadline(nextDeadline(hb));
      setLastCheckin(hb.last_check_in ?? null);
      setHeartbeatArmed(hb.armed);
    }).catch(() => { /* heartbeat may not exist yet */ });
    getReadiness().then((readiness) => {
      if (!cancelled) setRecovery(readiness);
    }).catch(() => { /* recovery status stays unknown */ });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  async function onCheckin() {
    setCheckinError("");
    try {
      await checkin();
      const [hb, vs] = await Promise.all([getHeartbeat(), getVaultStatus()]);
      setDeadline(nextDeadline(hb));
      setLastCheckin(hb.last_check_in ?? null);
      setStatus(vs.status);
      notify("success", "Checked in — deadline extended.");
    } catch (e) {
      setCheckinError(e instanceof Error ? e.message : "Check-in failed. Please try again.");
    }
  }

  const tone = stateTone(status);
  const heroLabel = status === "triggered" ? "RELEASED" : status === "grace" ? "GRACE PERIOD" : "ACTIVE";

  return (
    <main className="mx-auto max-w-5xl px-4 py-8 sm:py-10">
      <div className="page-heading">
        <div>
          <p className="eyebrow">Owner overview</p>
          <h1 className="page-title mt-2 text-balance">Your vault</h1>
        </div>
        <p className="supporting max-w-sm">A clear view of your check-in plan, private messages, and recovery readiness.</p>
      </div>

      {/* Hero — heartbeat countdown is the product's heartbeat */}
      <section className="surface-hero dashboard-deadline" aria-label="Vault status">
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="eyebrow">Vault status</p>
            <p className="mt-2 text-xl font-medium">{status === "triggered" ? "Released to your trusted people" : status === "grace" ? "Check-in needed" : "Your vault is active"}</p>
          </div>
          <StatusChip tone={tone} pulse={status === "grace"}>
            <span aria-live="polite">{heroLabel.toLowerCase()}</span>
          </StatusChip>
        </div>
        <div className="dashboard-deadline-body">
          <div>
            <p className="eyebrow">Next check-in</p>
            <p className="mt-3 font-mono text-4xl font-medium tabular-nums tracking-tight sm:text-5xl" aria-live="off">
              {formatCountdown(deadline, now)}
            </p>
            <p className="supporting mt-2">remaining</p>
          </div>
          <div className="flex flex-col items-start gap-3 sm:items-end">
            <button type="button" className="btn-primary min-w-40" onClick={onCheckin} disabled={status === "triggered"}>
              <CheckCircle2 className="h-4 w-4" />
              Check in now
            </button>
            <p className="text-xs text-faint">
              Last check-in: {lastCheckin ? new Date(lastCheckin).toLocaleString() : "Not checked in yet"}
            </p>
          </div>
        </div>
      </section>

      {checkinError && (
        <section className="surface-lg mt-4 !border-danger/50" role="alert" aria-live="polite">
          <h2 className="font-semibold text-danger">Check-in could not be completed</h2>
          <p className="mt-2 text-sm leading-relaxed">{checkinError}</p>
          {checkinError.toLowerCase().includes("recovery setup") && (
            <Link className="btn-secondary mt-4" href="/settings/security">Review recovery readiness</Link>
          )}
        </section>
      )}

      {/* Stat tiles */}
      <section className="dashboard-stats mt-4 grid gap-3 sm:grid-cols-3" aria-label="Vault summary">
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
            {recovery ? `${recovery.eligible_assignments} / ${recovery.total}` : "–"}
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
              {
                label: recovery === null
                  ? "Recovery status not checked"
                  : "Recovery ready for release (owner-reported)",
                ok: !!recovery?.initialized
                  && recovery.ceremony_status === "READY"
                  && recovery.quorum_assigned
                  && recovery.owner_reported_drill !== null,
              },
              {
                label: counts ? `${counts.beneficiaries} ${counts.beneficiaries === 1 ? "trusted person" : "trusted people"} assigned` : "Trusted people assigned",
                ok: (counts?.beneficiaries ?? 0) > 0,
              },
              {
                label: heartbeatArmed === null ? "Heartbeat status not checked" : "Heartbeat armed",
                ok: heartbeatArmed === true,
              },
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
