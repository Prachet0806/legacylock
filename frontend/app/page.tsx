"use client";

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
    <main style={{ padding: 24, fontFamily: "sans-serif" }}>
      <h1>LegacyLock (monorepo)</h1>
      <p>
        Frontend was previously a git submodule and is now vendored into this
        repo (squashed). Full vault UI to be reimplemented; auth uses
        HttpOnly cookies with <code>credentials: include</code>.
      </p>
      <button onClick={checkHealth}>Check API health</button>
      <pre>{status}</pre>
    </main>
  );
}
