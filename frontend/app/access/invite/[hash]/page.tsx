"use client";

// Beneficiary invitation accept: status -> accept (cookies carry the session)
// -> link to recovery. No tokens ever touch JS state or storage.
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowRight, CheckCircle2, MailOpen, ShieldCheck } from "lucide-react";
import { acceptInvite, getInviteStatus } from "../../../../lib/client";
import { Spinner, StatusChip } from "../../../../components/ui";

export default function InvitePage() {
  const raw = useParams()?.hash;
  const hash = Array.isArray(raw) ? raw[0] : (raw as string | undefined);
  const [status, setStatus] = useState<string>("loading…");
  const [expired, setExpired] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!hash) return;
    (async () => {
      try {
        const s = await getInviteStatus(hash);
        setStatus(s.invitation_status);
        setExpired(s.is_expired);
      } catch (e) {
        setErr(e instanceof Error ? e.message : "Invalid invitation");
        setStatus("invalid");
      }
    })();
  }, [hash]);

  async function onAccept() {
    setErr("");
    setBusy(true);
    try {
      await acceptInvite(hash!);
      setDone(true);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Accept failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-4 py-10">
      <div className="card flex flex-col gap-4">
        <div className="flex items-center gap-2">
          <MailOpen className="h-5 w-5 text-accent" />
          <h1 className="text-xl font-semibold">Beneficiary invitation</h1>
        </div>
        <StatusChip tone={expired || status === "invalid" ? "danger" : status === "accepted" ? "success" : "neutral"}>
          {status}{expired ? " (expired)" : ""}
        </StatusChip>
        {!done ? (
          <>
            <p className="text-sm text-muted">
              You have been named as a beneficiary. Accepting creates a short-lived access
              session in this browser. You will still need 2 recovery shares to decrypt
              anything — and only after the vault is released.
            </p>
            {err && <p role="alert" className="text-sm text-danger">{err}</p>}
            <button type="button" className="btn-primary w-full" disabled={busy || expired} onClick={onAccept}>
              {busy ? <Spinner /> : <CheckCircle2 className="h-4 w-4" />}
              {busy ? "Accepting…" : "Accept invitation"}
            </button>
          </>
        ) : (
          <>
            <p className="flex items-center gap-2 text-sm text-success">
              <CheckCircle2 className="h-4 w-4" />
              Accepted. Your access session is ready.
            </p>
            <Link href="/recovery" className="btn-primary w-full">
              Continue to recovery
              <ArrowRight className="h-4 w-4" />
            </Link>
          </>
        )}
      </div>
      <p className="mt-4 flex items-center gap-2 text-xs text-faint">
        <ShieldCheck className="h-4 w-4 shrink-0 text-success" />
        Invitation links are single-use and expire after 7 days.
      </p>
    </main>
  );
}
