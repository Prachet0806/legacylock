"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Eye, EyeOff, UserPlus, Vault as VaultIcon } from "lucide-react";
import { register } from "../../lib/api/public";
import { useToast } from "../../components/toast";

function messageOf(err: unknown): string {
  const msg = err instanceof Error ? err.message : "";
  if (msg.includes("403")) return "Invalid invitation code or registration disabled.";
  if (msg.includes("409")) return "An account with this email already exists. Try logging in.";
  if (msg.includes("422")) return "Check your entries — password must be 12+ characters.";
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
    <main className="mx-auto flex min-h-screen w-full max-w-md flex-col justify-center px-4 py-10">
      <div className="mb-6 flex items-center gap-2">
        <VaultIcon className="h-6 w-6 text-accent" />
        <span className="text-lg font-semibold">LegacyLock</span>
      </div>
      <h1 className="mb-1 text-2xl font-bold">Create owner account</h1>
      <p className="mb-6 text-sm text-muted">
        Invite-gated registration. You will verify your email before logging in.
      </p>
      {done ? (
        <div className="flex flex-col gap-4">
          <p role="status" className="text-sm text-success">
            Check your inbox for the verification link, then log in.
          </p>
          <button className="btn-primary w-full" onClick={() => router.push("/")}>
            Go to login
          </button>
        </div>
      ) : (
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
            <label className="label" htmlFor="password">Password (12+ characters)</label>
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
          <div>
            <label className="label" htmlFor="invite">Invite code</label>
            <input
              id="invite"
              className="input"
              type="text"
              autoComplete="off"
              placeholder="Ask your administrator"
              value={inviteCode}
              onChange={(e) => setInviteCode(e.target.value)}
              required
            />
          </div>
          {err && (
            <p role="alert" className="text-sm text-danger">{err}</p>
          )}
          <button type="submit" className="btn-primary w-full" disabled={busy}>
            <UserPlus className="h-4 w-4" />
            {busy ? "Registering…" : "Register"}
          </button>
        </form>
      )}
      <p className="mt-6 text-sm text-muted">
        Already have an account? <Link className="underline" href="/">Log in</Link>
      </p>
    </main>
  );
}
