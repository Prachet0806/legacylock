"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import {
  Eye,
  EyeOff,
  Lock,
  ShieldCheck,
  Vault as VaultIcon,
} from "lucide-react";
import { login } from "../lib/api";
import { resendVerification } from "../lib/api/public";
import { ApiError } from "../lib/api/transport";
import { HomeLoading } from "../components/home-loading";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [opening, setOpening] = useState(false);
  const [err, setErr] = useState("");
  const [unverified, setUnverified] = useState(false);
  const [resent, setResent] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    setUnverified(false);
    setBusy(true);
    try {
      await login(email, password);
    } catch (e) {
      if (e instanceof ApiError && e.status === 429) {
        setErr(e.message);
      } else if (e instanceof ApiError && e.status === 403 && e.message === "Email not verified") {
        setUnverified(true);
        setErr("Email not verified. Check your inbox for the link.");
      } else if (e instanceof ApiError && e.status === 403) {
        setErr(e.message);
      } else {
        setErr("Invalid email or password.");
      }
      setBusy(false);
      return;
    }
    setPassword("");
    setOpening(true);
    router.replace("/home");
  }

  async function onResend() {
    if (!email.trim()) return;
    await resendVerification(email.trim()).catch(() => undefined);
    setResent(true);
  }

  if (opening) return <HomeLoading message="Signed in. Opening your vault…" />;

  return (
    <main className="public-auth mx-auto grid min-h-screen w-full lg:grid-cols-[3fr_2fr]">
      {/* Brand panel */}
      <section className="auth-story relative hidden flex-col justify-center overflow-hidden border-r border-border bg-bg p-12 lg:flex">
        <div className="relative mx-auto flex w-full max-w-xl flex-col gap-16 py-12">
          <div className="flex items-center gap-2.5">
            <span className="brand-mark"><VaultIcon className="h-4 w-4" /></span>
            <span className="text-lg font-semibold tracking-tight">LegacyLock</span>
          </div>
          <div className="flex flex-col gap-8">
            <div>
              <p className="eyebrow mb-4">A private archive for what matters</p>
              <h2 className="max-w-xl text-5xl font-medium leading-[1.08] tracking-tight text-balance">
                Keep your private messages ready for the people you trust.
              </h2>
              <p className="mt-5 max-w-md text-base leading-7 text-muted">
                Messages are encrypted in your browser. Recovery shares stay with the people and places you choose.
              </p>
            </div>
            <ul className="grid max-w-md grid-cols-1 gap-3 text-sm sm:grid-cols-3 lg:grid-cols-1">
              {["Encrypted in your browser", "Recovery shares held separately", "Release follows your check-in plan"].map((t, i) => (
                <li key={t} className="flex items-center gap-3 text-muted">
                  <span className="flex h-6 w-6 items-center justify-center rounded-md border border-border text-xs tabular-nums text-accent">0{i + 1}</span>
                  {t}
                </li>
              ))}
            </ul>
          </div>
          <p className="flex items-center gap-2 border-t border-border pt-5 text-sm text-muted">
            <ShieldCheck className="h-4 w-4 text-success" />
            Your vault passphrase unlocks your keys in this browser.
          </p>
        </div>
      </section>

      {/* Form panel */}
      <section className="flex flex-col justify-center px-4 py-10 sm:px-10">
        <div className="auth-form-inner mx-auto w-full max-w-sm">
          <div className="mb-6 flex items-center gap-2 lg:hidden">
            <span className="brand-mark"><VaultIcon className="h-4 w-4" /></span>
            <span className="text-lg font-semibold tracking-tight">LegacyLock</span>
          </div>
          <p className="text-sm text-muted">Owner access</p>
          <h1 className="mb-1 mt-1 text-2xl font-medium tracking-tight">Sign in to your vault</h1>
          <p className="mb-6 text-sm leading-relaxed text-muted">
            Sign in to check your vault status. Your vault passphrase unlocks your keys next.
          </p>
          <form onSubmit={onSubmit} className="flex flex-col gap-4">
            <div>
              <label className="label" htmlFor="email">Email</label>
              <input
                id="email"
                className="input"
                type="email"
                autoComplete="email"
                placeholder="owner@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div>
              <div className="mb-1 flex items-center justify-between">
                <label className="label !mb-0" htmlFor="password">Password</label>
              </div>
              <div className="relative">
                <input
                  id="password"
                  className="input pr-10"
                  type={show ? "text" : "password"}
                  autoComplete="current-password"
                  placeholder="Your login password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
                <button
                  type="button"
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded-lg p-1.5 text-muted hover:text-text"
                  onClick={() => setShow((v) => !v)}
                  aria-label={show ? "Hide password" : "Show password"}
                >
                  {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>
            {err && (
              <p role="alert" className="text-sm text-danger">{err}</p>
            )}
            {unverified && (
              <div className="flex flex-col gap-2">
                {resent ? (
                  <p role="status" className="text-sm text-muted">
                    If the account needs verification, an email has been sent.
                  </p>
                ) : (
                  <button type="button" className="btn-secondary w-full" onClick={onResend}>
                    Resend verification email
                  </button>
                )}
              </div>
            )}
            <button type="submit" className="btn-primary w-full" disabled={busy}>
              <Lock className="h-4 w-4" />
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </form>
          <div className="my-6 flex items-center gap-3 text-xs text-faint" aria-hidden="true">
            <span className="h-px flex-1 bg-border" />
            <ShieldCheck className="h-4 w-4" />
            Encrypted in this browser
            <span className="h-px flex-1 bg-border" />
          </div>
          <p className="text-xs leading-relaxed text-faint">
            New here?{" "}
            <Link className="underline" href="/register">Create an account</Link>.
          </p>
        </div>
      </section>
    </main>
  );
}
