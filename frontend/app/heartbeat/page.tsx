"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, History, Siren, Timer } from "lucide-react";
import { clsx } from "clsx";
import {
  checkin,
  getHeartbeat,
  getVaultStatus,
  manualTrigger,
  putHeartbeat,
  type HeartbeatConfig,
  type VaultStatus,
} from "../../lib/client";
import { Modal, Spinner, StatusChip } from "../../components/ui";
import { useToast } from "../../components/toast";

const STATES = ["active", "grace", "triggered"] as const;

function countdown(target: string | null): string {
  if (!target) return "—";
  const ms = new Date(target).getTime() - Date.now();
  if (ms <= 0) return "due now";
  const d = Math.floor(ms / 86400000);
  const h = Math.floor((ms % 86400000) / 3600000);
  return d > 0 ? `${d}d ${h}h` : `${h}h`;
}

export default function HeartbeatPage() {
  const { notify } = useToast();
  const [cfg, setCfg] = useState<HeartbeatConfig | null>(null);
  const [status, setStatus] = useState<VaultStatus | null>(null);
  const [intervalDays, setIntervalDays] = useState("30");
  const [graceDays, setGraceDays] = useState("7");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [showTrigger, setShowTrigger] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function refresh() {
    setCfg(await getHeartbeat());
    setStatus(await getVaultStatus());
  }
  useEffect(() => {
    refresh().catch((e) => setErr(e instanceof Error ? e.message : "Load failed"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function onSave() {
    try {
      await putHeartbeat({ interval_days: Number(intervalDays), grace_days: Number(graceDays) });
      await refresh();
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
      notify("success", "Vault triggered. Beneficiaries have been notified.");
    } catch {
      notify("error", "Trigger failed — wrong password?");
    } finally {
      setBusy(false);
    }
  }

  const state = status?.status ?? "active";
  const activeIdx = STATES.indexOf(state as (typeof STATES)[number]);

  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      <h1 className="mb-6 text-2xl font-bold">Heartbeat</h1>

      {/* State timeline */}
      <div className="card mb-4">
        <ol className="flex items-center" aria-label="Vault release timeline">
          {STATES.map((s, i) => (
            <li key={s} className="flex flex-1 items-center last:flex-none">
              <div className="flex flex-col items-center gap-1">
                <span
                  className={clsx(
                    "flex h-8 w-8 items-center justify-center rounded-full text-xs font-bold",
                    i < activeIdx && "bg-success text-black",
                    i === activeIdx && s === "active" && "bg-success text-black",
                    i === activeIdx && s === "grace" && "animate-pulse bg-warn text-black",
                    i === activeIdx && s === "triggered" && "bg-danger text-white",
                    i > activeIdx && "bg-raised text-muted",
                  )}
                >
                  {i + 1}
                </span>
                <span className={clsx("text-xs uppercase", i === activeIdx ? "text-text" : "text-faint")}>
                  {s}
                </span>
              </div>
              {i < STATES.length - 1 && (
                <div className={clsx("mx-2 h-0.5 flex-1", i < activeIdx ? "bg-success" : "bg-border")} />
              )}
            </li>
          ))}
        </ol>
      </div>

      {state === "grace" && (
        <div className="card mb-4 flex items-start gap-2 border-warn text-sm">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-warn" />
          <span>
            Check-ins were missed. Check in now to return to ACTIVE, or the vault releases
            automatically when the grace period ends.
          </span>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        {/* Status card */}
        <div className="card flex flex-col gap-2">
          <h2 className="flex items-center gap-2 font-semibold">
            <Timer className="h-4 w-4 text-accent" />
            Status
          </h2>
          <StatusChip tone={state === "triggered" ? "danger" : state === "grace" ? "warn" : "success"} pulse={state === "grace"}>
            {state.toUpperCase()}
          </StatusChip>
          <dl className="text-sm">
            <div className="flex justify-between py-1">
              <dt className="text-muted">Last check-in</dt>
              <dd>{cfg?.last_check_in ? new Date(cfg.last_check_in).toLocaleString() : "never"}</dd>
            </div>
            <div className="flex justify-between py-1">
              <dt className="text-muted">Next deadline</dt>
              <dd>{countdown(cfg?.next_deadline ?? null)}</dd>
            </div>
          </dl>
          <button type="button" className="btn-primary mt-2 text-sm" onClick={onCheckin}>
            <CheckCircle2 className="h-4 w-4" />
            Check in now
          </button>
        </div>

        {/* Schedule card */}
        <div className="card flex flex-col gap-3">
          <h2 className="flex items-center gap-2 font-semibold">
            <History className="h-4 w-4 text-accent" />
            Schedule
          </h2>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="label" htmlFor="interval">Check-in every (days)</label>
              <input id="interval" className="input" inputMode="numeric" value={intervalDays} onChange={(e) => setIntervalDays(e.target.value)} />
            </div>
            <div>
              <label className="label" htmlFor="grace">Grace period (days)</label>
              <input id="grace" className="input" inputMode="numeric" value={graceDays} onChange={(e) => setGraceDays(e.target.value)} />
            </div>
          </div>
          <p className="text-xs text-faint">
            Currently: every {cfg?.interval_days ?? "…"} days, {cfg?.grace_days ?? "…"} days grace.
          </p>
          <button type="button" className="btn-ghost mt-auto self-start text-sm" onClick={onSave}>
            Save schedule
          </button>
        </div>
      </div>

      {/* Danger zone */}
      <div className="card mt-4 border-danger">
        <h2 className="mb-1 flex items-center gap-2 font-semibold text-danger">
          <Siren className="h-4 w-4" />
          Release vault now
        </h2>
        <p className="mb-3 text-sm text-muted">
          Releases beneficiary access immediately. Requires your login password and explicit
          confirmation. Idempotent — triggering twice is safe.
        </p>
        <button
          type="button"
          className="btn-danger text-sm"
          disabled={state === "triggered"}
          onClick={() => setShowTrigger(true)}
        >
          Trigger vault…
        </button>
      </div>

      {err && <p role="alert" className="mt-4 text-sm text-danger">{err}</p>}

      {showTrigger && (
        <Modal title="Trigger vault release?" onClose={() => setShowTrigger(false)}>
          <p className="mb-4 text-sm text-muted">
            This notifies all beneficiaries immediately. Type your login password and confirm.
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
              className="h-4 w-4 accent-[#e55353]"
              checked={confirm}
              onChange={(e) => setConfirm(e.target.checked)}
            />
            I understand this releases beneficiary access
          </label>
          <div className="mt-4 flex justify-end gap-2">
            <button type="button" className="btn-ghost text-sm" onClick={() => setShowTrigger(false)}>
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
