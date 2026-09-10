"use client";

// Beneficiary invitation accept: GET status -> POST accept -> save token -> link to recovery.
import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { apiFetch } from "../../../../lib/api";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function InvitePage() {
  const raw = useParams()?.hash;
  const hash = Array.isArray(raw) ? raw[0] : (raw as string | undefined);
  const [status, setStatus] = useState<string>("loading…");
  const [err, setErr] = useState("");
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!hash) return;
    (async () => {
      try {
        const s = await apiFetch<{ invitation_status: string; is_expired: boolean }>(
          `/access/invite/${hash}/status`,
        );
        setStatus(`${s.invitation_status}${s.is_expired ? " (expired)" : ""}`);
      } catch (e) {
        setErr(e instanceof Error ? e.message : "Invalid invitation");
        setStatus("invalid");
      }
    })();
  }, [hash]);

  async function onAccept() {
    setErr("");
    try {
      const res = await fetch(`${API_URL}/access/invite/${hash}/accept`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) throw new Error(`Accept failed: ${res.status}`);
      const data = (await res.json()) as { access_token: string; beneficiary_id: number };
      // Beneficiary JWT is short-lived; sessionStorage keeps it tab-scoped (VMK/shares never stored).
      sessionStorage.setItem("legacylock_beneficiary_token", data.access_token);
      setDone(true);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Accept failed");
    }
  }

  return (
    <main style={{ padding: 24, maxWidth: 560 }}>
      <h1>Beneficiary invitation</h1>
      <p>Status: {status}</p>
      {!done ? (
        <button onClick={onAccept}>Accept invitation</button>
      ) : (
        <p>
          Accepted. Continue to <Link href="/recovery">recovery</Link> to submit shares.
        </p>
      )}
      {err && <p style={{ color: "red" }}>{err}</p>}
    </main>
  );
}
