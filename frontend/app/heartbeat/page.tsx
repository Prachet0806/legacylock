"use client";

import { useEffect, useState } from "react";
import { getHeartbeat, putHeartbeat, checkin, getVaultStatus, manualTrigger, type HeartbeatConfig, type VaultStatus } from "../../lib/client";

export default function HeartbeatPage() {
  const [cfg, setCfg] = useState<HeartbeatConfig | null>(null);
  const [status, setStatus] = useState<VaultStatus | null>(null);
  const [intervalDays, setIntervalDays] = useState("30");
  const [graceDays, setGraceDays] = useState("7");
  const [password, setPassword] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  async function refresh() {
    setCfg(await getHeartbeat());
    setStatus(await getVaultStatus());
  }
  useEffect(() => {
    refresh().catch((e) => setErr(e instanceof Error ? e.message : "Load failed"));
  }, []);

  return (
    <main style={{ padding: 24, maxWidth: 640 }}>
      <h1>Heartbeat + Trigger</h1>
      <p>Status: <strong>{status?.status ?? "…"}</strong></p>
      <p>Config: interval {cfg?.interval_days}d / grace {cfg?.grace_days}d / last check-in {cfg?.last_check_in ?? "never"}</p>
      <div style={{ display: "flex", gap: 8 }}>
        <input value={intervalDays} onChange={(e) => setIntervalDays(e.target.value)} placeholder="interval days" />
        <input value={graceDays} onChange={(e) => setGraceDays(e.target.value)} placeholder="grace days" />
        <button onClick={async () => {
          await putHeartbeat({ interval_days: Number(intervalDays), grace_days: Number(graceDays) });
          await refresh();
        }}>Save</button>
        <button onClick={async () => {
          await checkin();
          await refresh();
          setMsg("Checked in");
        }}>Check in now</button>
      </div>
      <h2>Manual trigger (re-auth + confirm)</h2>
      <input type="password" placeholder="Login password" value={password} onChange={(e) => setPassword(e.target.value)} />
      <button onClick={async () => {
        setErr("");
        try {
          await manualTrigger(password, true);
          await refresh();
          setMsg("Triggered");
        } catch (e) {
          setErr(e instanceof Error ? e.message : "Trigger failed");
        }
      }} style={{ marginLeft: 8 }}>Trigger vault</button>
      {msg && <p>{msg}</p>}
      {err && <p style={{ color: "red" }}>{err}</p>}
    </main>
  );
}
