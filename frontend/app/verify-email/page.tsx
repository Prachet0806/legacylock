"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { resendVerification, verifyEmail } from "../../lib/api/public";

function VerifyInner() {
  const params = useSearchParams();
  const initialQueryToken=useRef(params.get("token")??"");
  const [token, setToken] = useState("");
  const [state, setState] = useState<"idle" | "busy" | "ok" | "fail">("idle");
  const [email, setEmail] = useState("");
  const [resent, setResent] = useState(false);
  const [credentialReady,setCredentialReady]=useState(false);
  // Single-flight guard: the token is atomic single-use server-side, so a
  // second POST (e.g. React StrictMode's dev double-effect) would burn the
  // redemption and flip the UI to failure. Refs survive strict remounts.
  const attempted = useRef(false);

  useEffect(() => {
    const read=()=>{
      const value=new URLSearchParams(window.location.hash.slice(1)).get("token") ?? initialQueryToken.current;
      initialQueryToken.current="";
      if(value) {setToken(value);attempted.current=false;setState("idle");}
      window.history.replaceState(null, "", "/verify-email");
    };
    read();
    window.addEventListener("hashchange",read);
    setCredentialReady(true);
    return ()=>window.removeEventListener("hashchange",read);
  }, []);

  async function confirmVerification() {
    if (!token || attempted.current) return;
    attempted.current = true;
    setState("busy");
    try { await verifyEmail(token); setState("ok"); }
    catch { setState("fail"); }
    finally { setToken(""); }
  }

  async function onResend(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    await resendVerification(email.trim()).catch(() => undefined);
    setResent(true);
  }

  return (
    <main data-credential-ready={credentialReady} className="mx-auto flex min-h-screen w-full max-w-md flex-col justify-center px-4 py-10">
      <h1 className="mb-2 text-2xl font-bold">Email verification</h1>
      {state === "idle" && <button className="btn-primary" disabled={!token} onClick={confirmVerification}>Confirm email verification</button>}
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
