"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { resendVerification, verifyEmail } from "../../lib/api/public";

function VerifyInner() {
  const router = useRouter();
  const params = useSearchParams();
  const token = params.get("token") ?? "";
  const [state, setState] = useState<"idle" | "busy" | "ok" | "fail">("idle");
  const [email, setEmail] = useState("");
  const [resent, setResent] = useState(false);
  // Single-flight guard: the token is atomic single-use server-side, so a
  // second POST (e.g. React StrictMode's dev double-effect) would burn the
  // redemption and flip the UI to failure. Refs survive strict remounts.
  const attempted = useRef(false);

  useEffect(() => {
    if (!token) {
      // After a successful scrub the token reads empty on rerender — that is
      // not a failure. Only fresh loads without a token fail here.
      if (!attempted.current) setState("fail");
      return;
    }
    if (attempted.current) return;
    attempted.current = true;
    setState("busy");
    verifyEmail(token)
      .then(() => setState("ok"))
      .catch(() => setState("fail"))
      .finally(() => {
        // Remove the credential from the URL/history immediately after use
        // via Next's router (a raw history.replaceState is fought by the App
        // Router's own history patching and leaves the token in place).
        router.replace("/verify-email", { scroll: false });
      });
  }, [token, router]);

  async function onResend(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    await resendVerification(email.trim()).catch(() => undefined);
    setResent(true);
  }

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-md flex-col justify-center px-4 py-10">
      <h1 className="mb-2 text-2xl font-bold">Email verification</h1>
      {state === "busy" && <p className="text-sm text-muted">Verifying…</p>}
      {state === "ok" && (
        <div className="flex flex-col gap-4">
          <p role="status" className="text-sm text-success">
            Verified. You can now log in.
          </p>
          <Link className="btn-primary w-full text-center" href="/">
            Go to login
          </Link>
        </div>
      )}
      {state === "fail" && (
        <div className="flex flex-col gap-4">
          <p role="alert" className="text-sm text-danger">
            This link is invalid or expired. Request a fresh one below.
          </p>
          {resent ? (
            <p role="status" className="text-sm text-muted">
              If the account needs verification, an email has been sent.
            </p>
          ) : (
            <form onSubmit={onResend} className="flex flex-col gap-3">
              <label className="label" htmlFor="email">Account email</label>
              <input
                id="email"
                className="input"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
              <button type="submit" className="btn-primary w-full">
                Resend verification
              </button>
            </form>
          )}
          <Link className="text-sm text-muted underline" href="/">
            Back to login
          </Link>
        </div>
      )}
    </main>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense>
      <VerifyInner />
    </Suspense>
  );
}
