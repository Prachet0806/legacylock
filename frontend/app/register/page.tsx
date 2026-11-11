"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Check, Eye, EyeOff, MailCheck, ShieldCheck, UserPlus, Vault as VaultIcon } from "lucide-react";
import { register } from "../../lib/api/public";
import { ApiError } from "../../lib/api/transport";
import { useToast } from "../../components/toast";

function messageOf(err: unknown): string {
  const msg = err instanceof Error ? err.message : "";
  if (err instanceof ApiError && err.status === 429) return err.message;
  if (err instanceof ApiError && err.status === 403) return "Invalid invitation code or registration disabled.";
  if (err instanceof ApiError && err.status === 409) return "Registration could not complete. Try again.";
  if (err instanceof ApiError && err.status === 422) return "Check your entries — password must be 12+ characters.";
  return "Registration failed. Try again.";
}

export default function RegisterPage() {
  const router = useRouter();
  const { notify } = useToast();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [done, setDone] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    if (password !== confirm) {
      setErr("Passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await register(email.trim(), password, inviteCode.trim());
      setDone(true);
      notify("success", "Registered. Check your inbox to verify.");
    } catch (e) {
      setErr(messageOf(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="public-auth mx-auto grid min-h-screen w-full lg:grid-cols-[3fr_2fr]">
      <section className="auth-story relative hidden flex-col justify-center overflow-hidden border-r border-border bg-bg p-12 lg:flex">
        <div className="relative mx-auto flex w-full max-w-xl flex-col gap-16 py-12">
          <Link href="/" className="flex items-center gap-2.5 text-lg font-semibold tracking-tight">
            <span className="brand-mark"><VaultIcon className="h-4 w-4" /></span>
            <span>LegacyLock</span>
          </Link>
          <div className="flex flex-col gap-8">
            <div>
              <p className="eyebrow mb-4">A considered start</p>
              <h2 className="max-w-xl text-5xl font-medium leading-[1.08] tracking-tight text-balance">
                Make room for what you want to leave behind.
              </h2>
              <p className="mt-5 max-w-md text-base leading-7 text-muted">
                Create an owner account, verify your email, then sign in to set up your vault from the dashboard.
              </p>
            </div>
            <ol className="grid max-w-md gap-3 text-sm">
              {[
                { title: "Create your account", detail: "Use an invitation code to register." },
                { title: "Verify your email", detail: "Confirm the address before signing in." },
                { title: "Open your dashboard", detail: "Set up your vault after sign-in." },
              ].map((step, index) => (
                <li key={step.title} className="flex items-start gap-3 text-muted">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-border text-xs tabular-nums text-accent">0{index + 1}</span>
                  <span className="pt-0.5"><span className="text-text">{step.title}</span><span className="mt-1 block text-xs text-faint">{step.detail}</span></span>
                </li>
              ))}
            </ol>
          </div>
          <p className="flex items-center gap-2 border-t border-border pt-5 text-sm text-muted">
            <ShieldCheck className="h-4 w-4 text-success" />
            Your vault passphrase unlocks your keys in this browser.
          </p>
        </div>
      </section>

      <section className="flex flex-col justify-center px-4 py-10 sm:px-10">
        <div className="auth-form-inner mx-auto w-full max-w-sm">
          <div className="mb-7 flex items-center gap-2.5 lg:hidden">
            <span className="brand-mark"><VaultIcon className="h-4 w-4" /></span>
            <span className="text-lg font-semibold tracking-tight">LegacyLock</span>
          </div>
          <p className="eyebrow">Invitation required</p>
          <h1 className="mt-2 text-2xl font-medium tracking-tight">Create your owner account</h1>
          <p className="mt-2 text-sm leading-6 text-muted">
            Register with your invitation code. After email verification, sign in and set up your vault from the dashboard.
          </p>
          <ol className="registration-steps mt-5 grid grid-cols-2 gap-2" aria-label="Account setup steps">
            {[
              { number: "01", label: "Account", active: true },
              { number: "02", label: "Verify email", active: false },
            ].map((step) => (
              <li key={step.number} className={step.active ? "registration-step is-current" : "registration-step"}>
                <span>{step.number}</span>
                <span>{step.label}</span>
              </li>
            ))}
          </ol>

          {done ? (
            <div className="account-success mt-7 rounded-xl border border-border bg-surface p-5">
              <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-success/10 text-success"><MailCheck className="h-5 w-5" /></span>
              <h2 className="mt-4 text-base font-medium">Check your inbox</h2>
              <p role="status" className="mt-2 text-sm leading-6 text-muted">
                Your account is registered. Follow the verification link in your email, then sign in.
              </p>
              <button className="btn-primary mt-5 w-full" onClick={() => router.push("/")}>
                Go to sign in
              </button>
            </div>
          ) : (
            <form onSubmit={onSubmit} className="account-form mt-5 flex flex-col">
              <p className="mb-1 text-sm font-medium">Account details</p>
              <div>
                <label className="label" htmlFor="email">Email</label>
                <input
                  id="email"
                  className="input"
                  type="email"
                  autoComplete="email"
                  placeholder="you@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              </div>
              <div>
                <label className="label" htmlFor="password">Password</label>
                <div className="relative">
                  <input
                    id="password"
                    className="input pr-10"
                    type={show ? "text" : "password"}
                    autoComplete="new-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    minLength={12}
                    aria-describedby="password-hint"
                  />
                  <button
                    type="button"
                    className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-muted hover:text-text"
                    onClick={() => setShow((v) => !v)}
                    aria-label={show ? "Hide password" : "Show password"}
                  >
                    {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
                <p id="password-hint" className="mt-2 text-xs text-faint">Use at least 12 characters</p>
              </div>
              <div>
                <label className="label" htmlFor="confirm">Confirm password</label>
                <input
                  id="confirm"
                  className="input"
                  type={show ? "text" : "password"}
                  autoComplete="new-password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  required
                />
              </div>
              <div className="invite-field">
                <p className="mb-3 text-sm font-medium">Invitation</p>
                <label className="label" htmlFor="invite">Invitation code</label>
                <input
                  id="invite"
                  className="input"
                  type="text"
                  autoComplete="off"
                  placeholder="Enter your code"
                  value={inviteCode}
                  onChange={(e) => setInviteCode(e.target.value)}
                  required
                />
              </div>
              {err && <p role="alert" className="text-sm text-danger">{err}</p>}
              <button type="submit" className="btn-primary w-full" disabled={busy}>
                <UserPlus className="h-4 w-4" />
                {busy ? "Creating account…" : "Create account"}
              </button>
            </form>
          )}
          <p className="mt-6 text-sm text-muted">
            Already have an account? <Link className="underline" href="/">Sign in</Link>
          </p>
          <p className="mt-8 flex items-center gap-2 border-t border-border pt-4 text-xs text-faint lg:hidden">
            <Check className="h-3.5 w-3.5 text-success" />
            Account creation requires an invitation code.
          </p>
        </div>
      </section>
    </main>
  );
}
