"use client";

import Link from "next/link";
import { useState } from "react";
import { apiFetch } from "../lib/api";

export default function Dashboard() {
  const [status, setStatus] = useState<string>("");

  async function checkHealth() {
    try {
      const res = await apiFetch("/health");
      setStatus(JSON.stringify(res));
    } catch (e) {
      setStatus(e instanceof Error ? e.message : "error");
    }
  }

  return (
    <main style={{ padding: 24, maxWidth: 720 }}>
      <h1>LegacyLock (MVP)</h1>
      <p>Zero-knowledge vault — client-side encryption, Shamir 2-of-3, heartbeat release.</p>
      <nav style={{ display: "flex", gap: 12, flexWrap: "wrap", margin: "16px 0" }}>
        <Link href="/login">Login</Link>
        <Link href="/vault">Vault</Link>
        <Link href="/vault/setup">Setup</Link>
        <Link href="/beneficiaries">Beneficiaries</Link>
        <Link href="/heartbeat">Heartbeat</Link>
        <Link href="/recovery">Recovery</Link>
      </nav>
      <button onClick={checkHealth}>Check API health</button>
      <pre>{status}</pre>
    </main>
  );
}
