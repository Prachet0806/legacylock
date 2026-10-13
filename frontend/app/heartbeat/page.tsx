"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, ArrowRight, CheckCircle2, Siren } from "lucide-react";
import { clsx } from "clsx";
import {
  checkin,
  getHeartbeat,
  getVaultStatus,
  manualTrigger,
  nextDeadline,
  putHeartbeat,
  type HeartbeatConfig,
  type VaultStatus,
} from "../../lib/client";
import { Modal, Spinner, StatusChip } from "../../components/ui";
import { StateTimeline, formatCountdown, stateTone } from "../../components/vault-ui";
import { useToast } from "../../components/toast";

export default function HeartbeatPage() {
  const { notify } = useToast();
  const [cfg, setCfg] = useState<HeartbeatConfig | null>(null);
  const [status, setStatus] = useState<VaultStatus | null>(null);
  const [intervalDays, setIntervalDays] = useState("30");
  const [graceDays, setGraceDays] = useState("7");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [showTrigger, setShowTrigger] = useState(false);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [now, setNow] = useState(() => Date.now());

  async function refresh() {
    setCfg(await getHeartbeat());
    setStatus(await getVaultStatus());
  }
  useEffect(() => {
    refresh()
      .catch((e) => setErr(e instanceof Error ? e.message : "Load failed"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  async function onSave() {
    try {
      await putHeartbeat({ interval_days: Number(intervalDays), grace_days: Number(graceDays) });
      await refresh();
      setEditing(false);
      notify("success", "Heartbeat schedule saved.");
    } catch {
      notify("error", "Save failed. Check the values.");
    }
  }

  async function onCheckin() {
    try {
      await checkin();
      await refresh();
      notify("success", "Checked in — deadline extended.");
    } catch {
      notify("error", "Check-in failed.");
    }
  }

  async function onTrigger() {
    setBusy(true);
    try {
      await manualTrigger(password, true);
      setShowTrigger(false);
      setPassword("");
      setConfirm(false);
      await refresh();
      notify("success", "Vault released. Notices have been queued for accepted beneficiaries.");
    } catch(e) {
      notify("error", e instanceof Error ? e.message : "Trigger failed");
    } finally {
      setPassword("");
      setBusy(false);
    }
  }

  const state = status?.status ?? null;

  if (loading) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-8" aria-busy="true" aria-label="Loading heartbeat">
        <h1 className="page-title">Heartbeat</h1>
        <div className="surface-lg mt-6 animate-pulse">
          <div className="mx-auto h-6 w-1/3 rounded-xl bg-raised" />
          <div className="mx-auto mt-3 h-10 w-2/3 rounded-xl bg-raised" />
        </div>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      <p className="supporting">Heartbeat</p>
      <h1 className="page-title mt-1">Your vault is {state === "grace" ? "waiting" : state === "triggered" ? "released" : "active"}</h1>
      {status?.release_hold && <p role="status" className="mt-3 text-sm text-warn">Automatic and manual releases are temporarily held by the operator. You can still check in.</p>}
      {state !== "triggered" && !status?.armed && <p className="mt-3 text-sm text-muted">Heartbeat release is not armed. Your first check-in arms it.</p>}
      <p className="supporting mt-2">
        {cfg?.last_check_in
          ? `You last checked in ${new Date(cfg.last_check_in).toLocaleString()}.`
          : "You haven't checked in yet."}
      </p>

      {/* Signature hero */}
      <section className="surface-hero mt-6" aria-label="Heartbeat status">
        <StatusChip tone={stateTone(state)} pulse={state === "grace"} className="mx-auto">
          {(state ?? "unknown").toUpperCase()}
        </StatusChip>
        <p className="mt-6 font-mono text-5xl font-bold tabular-nums tracking-tight" aria-live="off">
          {formatCountdown(nextDeadline(cfg), now)}
        </p>
        <p className="supporting mt-2">until check-in</p>
        <button type="button" className="btn-primary mt-6 min-w-44" disabled={state === "triggered"} onClick={onCheckin}>
          <CheckCircle2 className="h-4 w-4" />
          Check in now
        </button>
      </section>

      {/* State machine */}
      <section className="surface-lg mt-4" aria-label="Release process">
        <StateTimeline state={state} />
        <div className="mt-5 space-y-1.5 text-center text-xs text-faint">
          <p>ACTIVE <span className="mx-1">↓</span> missed deadline</p>
          <p>GRACE <span className="mx-1">↓</span> grace expires</p>
          <p>TRIGGERED <span className="mx-1">→</span> trusted people can recover</p>
        </div>
      </section>

      {state === "grace" && (
        <div className="surface-lg mt-4 flex items-start gap-2.5 !border-warn/60" role="alert">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-warn" />
          <p className="text-sm leading-relaxed">
            Check-ins were missed. Check in now to return to ACTIVE, or the vault releases
            automatically when the grace period ends.
          </p>
        </div>
      )}

      {/* Schedule */}
      <section className="surface-lg mt-4">
        <div className="flex items-center justify-between gap-3">
          <h2 className="font-semibold">Schedule</h2>
          {!editing && (
            <button type="button" className="inline-flex items-center gap-1 text-sm text-muted hover:text-text" onClick={() => {
              setIntervalDays(String(cfg?.interval_days ?? 30));
              setGraceDays(String(cfg?.grace_days ?? 7));
              setEditing(true);
            }}>
              Edit schedule
              <ArrowRight className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
        {!editing ? (
          <dl className="mt-4 grid grid-cols-2 gap-3">
            <div className="rounded-xl bg-raised/60 p-4">
              <dt className="text-xs text-faint">Check-in every</dt>
              <dd className="mt-1 text-xl font-semibold">{cfg?.interval_days ?? "…"} days</dd>
            </div>
            <div className="rounded-xl bg-raised/60 p-4">
              <dt className="text-xs text-faint">Grace period</dt>
              <dd className="mt-1 text-xl font-semibold">{cfg?.grace_days ?? "…"} days</dd>
            </div>
          </dl>
        ) : (
          <div className="mt-4">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label" htmlFor="interval">Check-in every (days)</label>
                <input id="interval" className="input" inputMode="numeric" value={intervalDays} onChange={(e) => setIntervalDays(e.target.value)} />
              </div>
              <div>
                <label className="label" htmlFor="grace">Grace period (days)</label>
                <input id="grace" className="input" inputMode="numeric" value={graceDays} onChange={(e) => setGraceDays(e.target.value)} />
              </div>
            </div>
            <div className="mt-3 flex gap-2">
              <button type="button" className="btn-primary text-sm" onClick={onSave}>
                Save schedule
              </button>
              <button type="button" className="btn-ghost text-sm" onClick={() => setEditing(false)}>
                Cancel
              </button>
            </div>
          </div>
        )}
      </section>

      {/* Danger zone */}
      <section className="surface-lg mt-4 !border-danger/50">
        <h2 className="flex items-center gap-2 font-semibold text-danger">
          <Siren className="h-4 w-4" />
          Release vault now
        </h2>
        <p className="supporting mt-1">
          Releases access for your trusted people immediately. Requires your login password and explicit
          confirmation. Safe to trigger twice.
        </p>
        <button
          type="button"
          className="btn-danger mt-3 text-sm"
          disabled={state === "triggered"}
          onClick={() => setShowTrigger(true)}
        >
          Trigger vault…
        </button>
      </section>

      {err && <p role="alert" className="mt-4 text-sm text-danger">{err}</p>}

      {showTrigger && (
        <Modal title="Trigger vault release?" onClose={() => {setShowTrigger(false);setPassword("");setConfirm(false);}}>
          <p className="mb-4 text-sm leading-relaxed text-muted">
            This releases access and queues notices for accepted beneficiaries. Enter your login password and confirm.
          </p>
          <label className="label" htmlFor="trigger-pass">Login password</label>
          <input
            id="trigger-pass"
            type="password"
            className="input"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <label className="mt-3 flex cursor-pointer items-center gap-2 text-sm">
            <input
              type="checkbox"
              className={clsx("h-4 w-4 accent-[#e05c5c]")}
              checked={confirm}
              onChange={(e) => setConfirm(e.target.checked)}
            />
            I understand this releases access for my trusted people
          </label>
          <div className="mt-4 flex justify-end gap-2">
            <button type="button" className="btn-ghost text-sm" onClick={() => {setShowTrigger(false);setPassword("");setConfirm(false);}}>
              Cancel
            </button>
            <button
              type="button"
              className="btn-danger text-sm"
              disabled={busy || !confirm || !password}
              onClick={onTrigger}
            >
              {busy && <Spinner />}
              Trigger now
            </button>
          </div>
        </Modal>
      )}
    </main>
  );
}
