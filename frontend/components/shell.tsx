"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  HeartPulse,
  LayoutDashboard,
  LifeBuoy,
  Lock,
  LockOpen,
  LogOut,
  Menu,
  Settings,
  Users,
  Vault as VaultIcon,
  X,
} from "lucide-react";
import { clsx } from "clsx";
import { checkin, getAccessStatus, getMe, getVaultStatus, logout } from "../lib/client";
import { useVault } from "../lib/store/vault-context";
import { useToast } from "./toast";
import { Spinner, StatusChip } from "./ui";

const NAV = [
  { href: "/home", label: "Dashboard", icon: LayoutDashboard },
  { href: "/vault", label: "Vault", icon: VaultIcon },
  { href: "/beneficiaries", label: "Beneficiaries", icon: Users },
  { href: "/heartbeat", label: "Heartbeat", icon: HeartPulse },
  { href: "/recovery", label: "Recovery", icon: LifeBuoy },
  { href: "/settings", label: "Settings", icon: Settings },
];

// Public routes render without the app chrome. The login form lives at /,
// so / is public; everything else requires the shell.
const PUBLIC_ACCESS_PREFIX = "/access";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { notify } = useToast();
  const { unlocked, lock } = useVault();
  const [status, setStatus] = useState<string>("active");
  const [menuOpen, setMenuOpen] = useState(false);

  const isPublic = pathname === "/" || pathname?.startsWith(PUBLIC_ACCESS_PREFIX);
  // Explicit principal detection — no guessing from storage:
  // - owner session (GET /auth/me) admits every app route,
  // - beneficiary session (GET /access/status) admits /recovery only,
  // - everyone else is bounced to login. The server enforces auth on every
  //   API call regardless; this only decides whether to render the page.
  // /recovery is intentionally outside the owner group: it is the
  // beneficiary-authenticated route.
  const OWNER_ROUTES = ["/home", "/vault", "/beneficiaries", "/heartbeat", "/settings"];
  const isOwnerRoute = OWNER_ROUTES.some(
    (r) => pathname === r || pathname?.startsWith(`${r}/`),
  );
  const [authed, setAuthed] = useState(false);
  const [principal, setPrincipal] = useState<"owner" | "beneficiary">("owner");

  useEffect(() => {
    if (isPublic) return;
    let cancelled = false;
    (async () => {
      try {
        await getMe();
        if (!cancelled) {
          setPrincipal("owner");
          setAuthed(true);
        }
        return;
      } catch {
        // Not an owner — fall through to beneficiary check.
      }
      if (pathname === "/recovery") {
        try {
          await getAccessStatus();
          if (!cancelled) {
            setPrincipal("beneficiary");
            setAuthed(true);
          }
          return;
        } catch {
          // Not a beneficiary either.
        }
      }
      if (!cancelled) router.replace("/");
    })();
    return () => {
      cancelled = true;
    };
  }, [pathname, isPublic, router]);

  useEffect(() => {
    if (isPublic || !authed || principal !== "owner") return;
    getVaultStatus()
      .then((s) => setStatus(s.status))
      .catch(() => {});
  }, [pathname, isPublic, authed, principal]);

  async function onCheckin() {
    try {
      await checkin();
      const s = await getVaultStatus();
      setStatus(s.status);
      notify("success", "Checked in — deadline extended.");
    } catch {
      notify("error", "Check-in failed. Are you logged in?");
    }
  }

  async function onLogout() {
    try {
      await logout();
    } catch {
      /* cookie may already be gone */
    }
    lock();
    router.push("/");
  }

  if (isPublic) {
    return <div className="min-h-screen">{children}</div>;
  }

  if (!authed) {
    return (
      <div className="flex min-h-screen items-center justify-center gap-2 text-sm text-muted">
        <Spinner />
        Checking session…
      </div>
    );
  }

  const statusTone = status === "triggered" ? "danger" : status === "grace" ? "warn" : "success";

  const nav = (
    <nav className="flex flex-col gap-1">
      {NAV.map((item) => {
        const active = pathname === item.href;
        const Icon = item.icon;
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={() => setMenuOpen(false)}
            className={clsx(
              "flex items-center gap-3 rounded-md px-3 py-2 text-sm",
              active ? "bg-raised text-text" : "text-muted hover:bg-raised hover:text-text",
            )}
            aria-current={active ? "page" : undefined}
          >
            <Icon className="h-4 w-4" />
            {item.label}
          </Link>
        );
      })}
    </nav>
  );

  return (
    <div className="min-h-screen lg:flex">
      {/* Desktop sidebar */}
      <aside className="hidden w-60 shrink-0 flex-col gap-6 border-r border-border bg-surface p-4 lg:flex">
        <Link href="/home" className="flex items-center gap-2 px-1 text-base font-semibold">
          <VaultIcon className="h-5 w-5 text-accent" />
          LegacyLock
        </Link>
        {principal === "owner" ? (
          nav
        ) : (
          <p className="rounded-md bg-raised px-3 py-2 text-xs text-muted">
            Signed in as beneficiary — recovery only.
          </p>
        )}
        <div className="mt-auto flex flex-col gap-2 border-t border-border pt-4">
          <StatusChip tone={unlocked ? "success" : "neutral"}>
            {unlocked ? <LockOpen className="h-3 w-3" /> : <Lock className="h-3 w-3" />}
            {unlocked ? "Vault unlocked" : "Vault locked"}
          </StatusChip>
          {unlocked && (
            <button type="button" className="btn-ghost text-xs" onClick={lock}>
              Lock vault
            </button>
          )}
          <button type="button" className="btn-ghost text-xs" onClick={onLogout}>
            <LogOut className="h-3.5 w-3.5" />
            Log out
          </button>
        </div>
      </aside>

      <div className="min-w-0 flex-1">
        {/* Topbar */}
        <header className="sticky top-0 z-40 flex items-center gap-3 border-b border-border bg-bg/95 px-4 py-3 backdrop-blur">
          <button
            type="button"
            className="btn-ghost px-2 py-1 lg:hidden"
            onClick={() => setMenuOpen((v) => !v)}
            aria-label="Toggle menu"
          >
            {menuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
          {principal === "owner" && (
            <StatusChip tone={statusTone} pulse={status === "grace"}>
              {status.toUpperCase()}
            </StatusChip>
          )}
          <div className="ml-auto flex items-center gap-2">
            {principal === "owner" && (
              <button type="button" className="btn-ghost text-xs" onClick={onCheckin}>
                Check in
              </button>
            )}
            <button type="button" className="btn-ghost px-2 py-1 lg:hidden" onClick={onLogout} aria-label="Log out">
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </header>

        {/* Mobile menu */}
        {menuOpen && (
          <div className="border-b border-border bg-surface p-4 lg:hidden">
            <div className="mb-3 flex items-center gap-2 text-base font-semibold">
              <VaultIcon className="h-5 w-5 text-accent" />
              LegacyLock
            </div>
            {principal === "owner" ? (
              nav
            ) : (
              <p className="rounded-md bg-raised px-3 py-2 text-xs text-muted">
                Signed in as beneficiary — recovery only.
              </p>
            )}
          </div>
        )}

        {children}
      </div>
    </div>
  );
}
