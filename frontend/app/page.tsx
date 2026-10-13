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
import { useToast } from "../components/toast";

export default function LoginPage() {
  const router = useRouter();
  const { notify } = useToast();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
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
      notify("success", "Logged in.");
      router.push("/home");
    } catch (e) {
      const msg = e instanceof Error ? e.message : "";
      if (e instanceof ApiError && e.status === 403) {
        setUnverified(true);
        setErr("Email not verified. Check your inbox for the link.");
      } else {
        setErr("Invalid email or password.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function onResend() {
    if (!email.trim()) return;
    await resendVerification(email.trim()).catch(() => undefined);
    setResent(true);
  }

  return (
    <main className="mx-auto grid min-h-screen w-full max-w-6xl lg:max-w-7xl xl:max-w-full lg:grid-cols-2">
      {/* Brand panel */}
      <section className="relative hidden flex-col justify-center items-center text-center overflow-hidden border-r border-border bg-surface p-10 lg:flex">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute -left-24 -top-24 h-72 w-72 rounded-full bg-accent/10 blur-3xl"
        />
        <div
          aria-hidden="true"
          className="pointer-events-none absolute -bottom-32 -right-16 h-80 w-80 rounded-full bg-accent/[0.07] blur-3xl"
        />
        <div className="relative flex flex-col items-center gap-10 py-12">
          <div className="relative flex items-center gap-2">
            <VaultIcon className="h-7 w-7 text-accent" />
            <span className="text-xl font-semibold tracking-tight">LegacyLock</span>
          </div>
          <div className="relative flex flex-col items-center gap-6">
            <div className="flex flex-col items-center gap-4">
              <h2 className="max-w-md text-5xl font-bold leading-[1.05] tracking-tight text-balance">
                Your legacy.<br />Kept private.
              </h2>
              <div className="h-px w-16 bg-accent/60" aria-hidden="true" />
            </div>
            <ul className="flex flex-col items-center gap-5 text-base">
              {["Encrypted locally", "Recovery without trust", "Automatic release"].map((t) => (
                <li key={t} className="flex items-center gap-3 text-muted">
                  <span className="h-2 w-2 rounded-full bg-accent flex-shrink-0" aria-hidden="true" />
                  {t}
                </li>
              ))}
            </ul>
          </div>
          <p className="relative flex items-center gap-2 text-sm text-faint">
            <ShieldCheck className="h-4 w-4 text-success" />
            Zero-knowledge design — we can&apos;t read your data.
          </p>
        </div>
      </section>

      {/* Form panel */}
      <section className="flex flex-col justify-center px-4 py-10 sm:px-10">
        <div className="mx-auto w-full max-w-md">
          <div className="mb-6 flex items-center gap-2 lg:hidden">
            <VaultIcon className="h-6 w-6 text-accent" />
            <span className="text-lg font-semibold tracking-tight">LegacyLock</span>
          </div>
          <p className="text-sm text-muted">Welcome back</p>
          <h1 className="mb-1 mt-1 text-2xl font-semibold tracking-tight">Owner login</h1>
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
            🔒 Zero-knowledge design
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
