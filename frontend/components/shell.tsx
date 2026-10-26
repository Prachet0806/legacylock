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
  Settings,
  Users,
  Vault as VaultIcon,
} from "lucide-react";
import { clsx } from "clsx";
import { checkin, getAccessStatus, getCryptoMaterial, getHeartbeat, getMe, getVaultStatus, logout, revokeBeneficiarySession } from "../lib/client";
import { getReadiness } from "../lib/api/owner";
import {bindVault} from "../lib/crypto-session";
import { useVault } from "../lib/store/vault-context";
import { useToast } from "./toast";
import { Spinner, StatusChip } from "./ui";
import { VaultLockIndicator } from "./security";

const NAV_HOME = [
  { href: "/home", label: "Overview", icon: LayoutDashboard },
  { href: "/vault", label: "Vault", icon: VaultIcon },
  { href: "/beneficiaries", label: "People", icon: Users },
  { href: "/heartbeat", label: "Heartbeat", icon: HeartPulse },
];
const NAV_RECOVERY = [{ href: "/recovery", label: "Recovery", icon: LifeBuoy }];
const NAV_SYSTEM = [{ href: "/settings", label: "Settings", icon: Settings }];

// Bottom tabs for mobile (primary owner actions).
const TABS = [...NAV_HOME];

// Public routes render without the app chrome. The login form lives at /,
// so / is public; everything else requires the shell.
const PUBLIC_ACCESS_PREFIX = "/access";

function NavGroup({ title, items, pathname, onNav }: {
  title: string;
  items: typeof NAV_HOME;
  pathname: string | null;
  onNav?: () => void;
}) {
  return (
    <div>
      <p className="mb-1.5 px-3 text-[11px] font-medium uppercase tracking-[0.14em] text-faint">{title}</p>
      <nav className="flex flex-col gap-0.5" aria-label={title}>
        {items.map((item) => {
          const active = pathname === item.href || pathname?.startsWith(`${item.href}/`);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={onNav}
              className={clsx(
                "flex items-center gap-3 rounded-xl px-3 py-2 text-sm transition-colors",
                active ? "bg-raised font-medium text-text" : "text-muted hover:bg-raised/60 hover:text-text",
              )}
              aria-current={active ? "page" : undefined}
            >
              <Icon className={clsx("h-4 w-4", active && "text-accent")} />
              {item.label}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { notify } = useToast();
  const { unlocked, lock } = useVault();
  const [status, setStatus] = useState<string>("active");
  const [recoveryReady, setRecoveryReady] = useState<boolean | null>(null);
  const [heartbeatActive, setHeartbeatActive] = useState<boolean | null>(null);

  // /register + /verify-email must stay public: logged-out newcomers can only
  // create and verify accounts from outside any session.
  const isPublic =
    pathname === "/" ||
    pathname === "/register" ||
    pathname === "/verify-email" ||
    pathname?.startsWith(PUBLIC_ACCESS_PREFIX);
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
  const [sessionVersion, setSessionVersion] = useState(0);
  useEffect(() => { const changed=()=>{setAuthed(false);setSessionVersion(v=>v+1);}; window.addEventListener("legacylock-session-changed",changed); return ()=>window.removeEventListener("legacylock-session-changed",changed); }, []);
  const [principal, setPrincipal] = useState<"owner" | "beneficiary">("owner");

  useEffect(() => {
    if (isPublic) return;
    let cancelled = false;
    setAuthed(false);
    (async () => {
      if (pathname !== "/recovery") try {
        const me=await getMe();
        const material=await getCryptoMaterial().catch(()=>null);
        if (!cancelled) {
          bindVault(`owner:${me.id}`, material?.material_revision??0);
          setPrincipal("owner");
          setAuthed(true);
        }
        return;
      } catch {
        // Not an owner — fall through to beneficiary check.
      }
      if (pathname === "/recovery") {
        try {
          const status=await getAccessStatus();
          if (!cancelled) {
            bindVault(`beneficiary:${status.beneficiary_id}`,status.material_revision);
            setPrincipal("beneficiary");
            setAuthed(true);
          }
          return;
        } catch {
          // Not a beneficiary either.
        }
      }
      if (!cancelled) router.replace(pathname === "/recovery" ? "/access/login" : "/");
    })();
    return () => {
      cancelled = true;
    };
  }, [pathname, isPublic, router, sessionVersion]);

  useEffect(() => {
    if (isPublic || !authed || principal !== "owner") return;
    getVaultStatus()
      .then((s) => setStatus(s.status))
      .catch(() => {});
  }, [pathname, isPublic, authed, principal]);

  useEffect(() => {
    if (isPublic || !authed || principal !== "owner") {
      setRecoveryReady(null);
      setHeartbeatActive(null);
      return;
    }
    setRecoveryReady(null);
    setHeartbeatActive(null);
    let cancelled = false;
    getReadiness()
      .then((evidence) => {
        if (!cancelled) {
          setRecoveryReady(
            evidence.initialized
              && evidence.ceremony_status === "READY"
              && evidence.quorum_assigned
              && evidence.owner_reported_drill !== null,
          );
        }
      })
      .catch(() => { if (!cancelled) setRecoveryReady(null); });
    getHeartbeat()
      .then((heartbeat) => { if (!cancelled) setHeartbeatActive(heartbeat.armed); })
      .catch(() => { if (!cancelled) setHeartbeatActive(null); });
    return () => { cancelled = true; };
  }, [pathname, isPublic, authed, principal, sessionVersion]);

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
      await (principal === "beneficiary" ? revokeBeneficiarySession() : logout());
    } catch {
      /* cookie may already be gone */
    }
    lock();
    router.push(principal === "beneficiary" ? "/access/login" : "/");
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
  const isBeneficiary = principal !== "owner";
  const showBottomNav = !isPublic && authed && !isBeneficiary && isOwnerRoute;

  return (
    <div className="min-h-screen lg:flex">
      {/* Desktop sidebar */}
      <aside className="hidden w-60 shrink-0 flex-col gap-6 border-r border-border bg-surface/60 p-4 lg:flex">
        <Link href="/home" className="flex items-center gap-2 px-1 text-base font-semibold tracking-tight">
          <VaultIcon className="h-5 w-5 text-accent" />
          LegacyLock
        </Link>
        {isBeneficiary ? (
          <p className="rounded-xl bg-raised px-3 py-2 text-xs leading-relaxed text-muted">
            Signed in as beneficiary — recovery only.
          </p>
        ) : (
          <>
            <NavGroup title="Home" items={NAV_HOME} pathname={pathname} />
            <NavGroup title="Recovery" items={NAV_RECOVERY} pathname={pathname} />
            <NavGroup title="System" items={NAV_SYSTEM} pathname={pathname} />
          </>
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

      <div className="min-w-0 flex-1 pb-20 lg:pb-0">
        {/* Topbar */}
        <header className="sticky top-0 z-40 flex items-center gap-3 border-b border-border bg-bg/90 px-4 py-3 backdrop-blur">
          <Link href="/home" className="flex items-center gap-2 text-base font-semibold tracking-tight lg:hidden">
            <VaultIcon className="h-5 w-5 text-accent" />
            LegacyLock
          </Link>
          {principal === "owner" && (
            <div className="hidden sm:block">
              <StatusChip tone={statusTone} pulse={status === "grace"}>
                {status.toUpperCase()}
              </StatusChip>
            </div>
          )}
          <div className="ml-auto flex items-center gap-2">
            {principal === "owner" && (
              <button type="button" className="btn-ghost hidden !rounded-xl px-3 py-1.5 text-xs sm:inline-flex" disabled={status === "triggered"} onClick={onCheckin}>
                Check in
              </button>
            )}
            <VaultLockIndicator
              unlocked={unlocked}
              recoveryReady={recoveryReady}
              heartbeatActive={heartbeatActive}
              onLock={lock}
            />
            <button type="button" className="btn-ghost px-2 py-1 lg:hidden" onClick={onLogout} aria-label="Log out">
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </header>

        {children}

        {/* Mobile bottom navigation */}
        {showBottomNav && (
          <nav
            className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-surface/95 backdrop-blur lg:hidden"
            aria-label="Primary"
          >
            <div className="grid grid-cols-4">
              {TABS.map((item) => {
                const active = pathname === item.href || pathname?.startsWith(`${item.href}/`);
                const Icon = item.icon;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={clsx(
                      "flex flex-col items-center gap-1 py-2.5 text-[11px] transition-colors",
                      active ? "font-medium text-text" : "text-faint",
                    )}
                    aria-current={active ? "page" : undefined}
                  >
                    <Icon className={clsx("h-5 w-5", active && "text-accent")} />
                    {item.label}
                  </Link>
                );
              })}
            </div>
          </nav>
        )}
      </div>
    </div>
  );
}
