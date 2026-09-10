"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import {
  Eye,
  EyeOff,
  HeartPulse,
  KeyRound,
  Lock,
  ShieldCheck,
  Vault as VaultIcon,
} from "lucide-react";
import { login } from "../lib/api";
import { useToast } from "../components/toast";

const HIGHLIGHTS = [
  {
    icon: ShieldCheck,
    title: "Server-blind by design",
    hint: "AES-256-GCM encryption happens in your browser. The server stores ciphertext only.",
  },
  {
    icon: KeyRound,
    title: "Shamir 2-of-3 recovery",
    hint: "Your vault key splits into three shares. Any two reconstruct it — locally.",
  },
  {
    icon: HeartPulse,
    title: "Inactivity release",
    hint: "Missed check-ins move the vault through grace to release for your beneficiaries.",
  },
];

export default function LoginPage() {
  const router = useRouter();
  const { notify } = useToast();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      await login(email, password);
      notify("success", "Logged in.");
      router.push("/home");
    } catch {
      setErr("Invalid email or password.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto grid min-h-screen w-full max-w-6xl lg:grid-cols-2">
      {/* Brand panel */}
      <section className="relative hidden flex-col justify-between overflow-hidden border-r border-border bg-surface p-10 lg:flex">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute -left-24 -top-24 h-72 w-72 rounded-full bg-accent/15 blur-3xl"
        />
        <div
          aria-hidden="true"
          className="pointer-events-none absolute -bottom-32 -right-16 h-80 w-80 rounded-full bg-accent/10 blur-3xl"
        />
        <div className="relative flex items-center gap-2">
          <VaultIcon className="h-7 w-7 text-accent" />
          <span className="text-xl font-semibold">LegacyLock</span>
        </div>
        <div className="relative flex flex-col gap-8">
          <div className="flex flex-col gap-3">
            <h2 className="max-w-md text-3xl font-bold leading-tight">
              Your legacy, sealed with <span className="text-accent">zero knowledge</span>.
            </h2>
            <p className="max-w-md text-sm text-muted">
              Store sensitive messages encrypted and release them to your beneficiaries
              only after prolonged inactivity.
            </p>
          </div>
          <ul className="flex flex-col gap-5">
            {HIGHLIGHTS.map((h) => {
              const Icon = h.icon;
              return (
                <li key={h.title} className="flex items-start gap-3">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-raised">
                    <Icon className="h-4 w-4 text-accent" />
                  </span>
                  <span>
                    <span className="block text-sm font-medium">{h.title}</span>
                    <span className="block max-w-sm text-sm text-muted">{h.hint}</span>
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
        <p className="relative text-xs text-faint">
          Plaintext, passphrases, and raw shares never leave your browser.
        </p>
      </section>

      {/* Form panel */}
      <section className="flex flex-col justify-center px-4 py-10 sm:px-10">
        <div className="mx-auto w-full max-w-md">
          <div className="mb-6 flex items-center gap-2 lg:hidden">
            <VaultIcon className="h-6 w-6 text-accent" />
            <span className="text-lg font-semibold">LegacyLock</span>
          </div>
          <p className="text-sm text-muted">Welcome back</p>
          <h1 className="mb-1 mt-1 text-2xl font-bold">Owner login</h1>
          <p className="mb-6 text-sm text-muted">
            Your login authenticates you. Your vault passphrase (asked next) unlocks your keys.
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
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-muted hover:text-text"
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
            <button type="submit" className="btn-primary w-full" disabled={busy}>
              <Lock className="h-4 w-4" />
              {busy ? "Logging in…" : "Log in"}
            </button>
          </form>
          <div className="my-6 flex items-center gap-3 text-xs text-faint" aria-hidden="true">
            <span className="h-px flex-1 bg-border" />
            Protected by zero-knowledge encryption
            <span className="h-px flex-1 bg-border" />
          </div>
          <p className="flex items-start gap-2 text-xs text-faint">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-success" />
            <span>
              Sessions live in HttpOnly cookies. No account yet? Ask your administrator to
              run seed_dev_user.py — there is no public signup by design.
            </span>
          </p>
        </div>
      </section>
    </main>
  );
}
