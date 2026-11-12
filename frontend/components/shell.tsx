"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
  HeartPulse,
  LayoutDashboard,
  LifeBuoy,
  Lock,
  LockOpen,
  LogOut,
  Menu,
  Settings,
  Sun,
  Moon,
  Users,
  Vault as VaultIcon,
  X,
} from "lucide-react";
import { clsx } from "clsx";
import { checkin, getAccessStatus, getCryptoMaterial, getHeartbeat, getMe, getVaultStatus, logout, revokeBeneficiarySession } from "../lib/client";
import { getReadiness } from "../lib/api/owner";
import {bindVault, isUnlocked} from "../lib/crypto-session";
import { useVault } from "../lib/store/vault-context";
import { useToast } from "./toast";
import { Spinner, StatusChip } from "./ui";
import { VaultLockIndicator } from "./security";
import { ApiError } from "../lib/api/transport";
import { HomeLoading } from "./home-loading";

const NAV_HOME = [
  { href: "/home", label: "Overview", icon: LayoutDashboard },
  { href: "/vault", label: "Vault", icon: VaultIcon },
  { href: "/beneficiaries", label: "People", icon: Users },
  { href: "/heartbeat", label: "Heartbeat", icon: HeartPulse },
];
const NAV_RECOVERY = [{ href: "/settings/security", label: "Recovery readiness", icon: LifeBuoy }];
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
      <p className="mb-2 px-3 text-xs font-medium text-faint">{title}</p>
      <nav className="flex flex-col gap-1" aria-label={title}>
        {items.map((item) => {
          const active = pathname === item.href || (item.href !== "/settings" && pathname?.startsWith(`${item.href}/`));
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={onNav}
              className={clsx(
                "flex min-h-9 items-center gap-3 rounded-lg border border-transparent px-3 py-1.5 text-sm transition-colors",
                active ? "border-border bg-raised font-medium text-text" : "text-muted hover:bg-raised/60 hover:text-text",
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

function ThemeToggle({ theme, onToggle, floating = false }: {
  theme: "dark" | "light";
  onToggle: () => void;
  floating?: boolean;
}) {
  const isLight = theme === "light";
  const Icon = isLight ? Sun : Moon;
  return (
    <button
      type="button"
      className={clsx(
        "btn h-9 gap-2 rounded-full border border-border px-3 text-xs text-text hover:border-accent hover:shadow-sm active:border-accent",
        floating ? "fixed right-5 top-5 z-50 bg-bg shadow-sm" : "bg-transparent",
      )}
      onClick={onToggle}
      aria-label={`Switch to ${isLight ? "dark" : "light"} mode`}
      aria-pressed={isLight}
      title={`Switch to ${isLight ? "dark" : "light"} mode`}
    >
      <Icon className="h-4 w-4 text-accent" aria-hidden="true" />
      <span>{isLight ? "Light" : "Dark"}<span className="hidden sm:inline"> mode</span></span>
    </button>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { notify } = useToast();
  const { unlocked, lock } = useVault();
  const [status, setStatus] = useState<string | null>(null);
  const [vaultInitialized, setVaultInitialized] = useState<boolean | null>(null);
  const [recoveryReady, setRecoveryReady] = useState<boolean | null>(null);
  const [heartbeatActive, setHeartbeatActive] = useState<boolean | null>(null);
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => setMobileMenuOpen(false), [pathname]);
  useEffect(() => {
    if (!mobileMenuOpen) return;
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMobileMenuOpen(false);
    };
    window.addEventListener("keydown", onEscape);
    return () => window.removeEventListener("keydown", onEscape);
  }, [mobileMenuOpen]);

  useEffect(() => {
    const saved = window.localStorage.getItem("legacylock-theme");
    const selected = saved === "light" ? "light" : "dark";
    document.documentElement.dataset.theme = selected;
    setTheme(selected);
  }, []);

  function toggleTheme() {
    const selected = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = selected;
    window.localStorage.setItem("legacylock-theme", selected);
    setTheme(selected);
  }

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
  const [authError, setAuthError] = useState("");
  const [sessionVersion, setSessionVersion] = useState(0);
  useEffect(() => { const changed=()=>{setAuthed(false);setSessionVersion(v=>v+1);}; window.addEventListener("legacylock-session-changed",changed); return ()=>window.removeEventListener("legacylock-session-changed",changed); }, []);
  useEffect(() => {
    const expired = (event: Event) => {
      const principal = (event as CustomEvent<"owner" | "beneficiary">).detail;
      if (principal !== (pathname === "/recovery" ? "beneficiary" : "owner")) return;
      setAuthed(false);
      router.replace(pathname === "/recovery" ? "/access/login" : "/");
    };
    window.addEventListener("legacylock-session-expired", expired);
    return () => window.removeEventListener("legacylock-session-expired", expired);
  }, [pathname, router]);
  const [principal, setPrincipal] = useState<"owner" | "beneficiary">("owner");
  const previousPath = useRef(pathname);

  useEffect(() => {
    const leavingSetup = previousPath.current === "/vault/setup" && pathname !== "/vault/setup";
    previousPath.current = pathname;
    if (leavingSetup && isUnlocked()) lock();
    if (isPublic) return;
    let cancelled = false;
    setAuthed(false);
    setAuthError("");
    (async () => {
      if (pathname !== "/recovery") try {
        const [me, material] = await Promise.all([
          getMe(),
          getCryptoMaterial().catch(() => null),
        ]);
        if (!cancelled) {
          bindVault(`owner:${me.id}`, material?.material_revision??0);
          setPrincipal("owner");
          setAuthed(true);
        }
        return;
      } catch (e) {
        if (e instanceof ApiError && e.status === 429) {
          if (!cancelled) setAuthError(e.message);
          return;
        }
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
        } catch (e) {
          if (e instanceof ApiError && e.status === 429) {
            if (!cancelled) setAuthError(e.message);
            return;
          }
          // Not a beneficiary either.
        }
      }
      if (!cancelled) router.replace(pathname === "/recovery" ? "/access/login" : "/");
    })();
    return () => {
      cancelled = true;
    };
  }, [pathname, isPublic, router, sessionVersion, lock]);

  useEffect(() => {
    if (isPublic || !authed || principal !== "owner") return;
    setStatus(null);
    getVaultStatus()
      .then((s) => setStatus(s.status))
      .catch(() => {});
  }, [pathname, isPublic, authed, principal]);

  useEffect(() => {
    if (isPublic || !authed || principal !== "owner") {
      setVaultInitialized(null);
      setRecoveryReady(null);
      setHeartbeatActive(null);
      return;
    }
    setVaultInitialized(null);
    setRecoveryReady(null);
    setHeartbeatActive(null);
    let cancelled = false;
    getReadiness()
      .then((evidence) => {
        if (!cancelled) {
          setVaultInitialized(evidence.initialized);
          setRecoveryReady(
            evidence.initialized
              && evidence.ceremony_status === "READY"
              && evidence.quorum_assigned
              && evidence.owner_reported_drill !== null,
          );
        }
      })
      .catch(() => { if (!cancelled) { setVaultInitialized(null); setRecoveryReady(null); } });
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
    } catch (e) {
      notify("error", e instanceof Error ? e.message : "Check-in failed.");
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
    return (
      <div className="public-page min-h-screen">
        <ThemeToggle theme={theme} onToggle={toggleTheme} floating />
        {children}
      </div>
    );
  }

  if (!authed) {
    if (!authError && pathname === "/home") return <HomeLoading />;
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 px-6 text-center text-sm text-muted">
        {authError ? <>
          <p role="alert">{authError}</p>
          <button type="button" className="btn-secondary" onClick={() => setSessionVersion((v) => v + 1)}>Try again</button>
        </> : <><Spinner />Checking session…</>}
      </div>
    );
  }

  const statusTone = status === null || vaultInitialized === false || (heartbeatActive === false && status === "active")
    ? "neutral" : status === "triggered" ? "danger" : status === "grace" ? "warn" : "success";
  const statusLabel = vaultInitialized === false ? "Setup needed"
    : heartbeatActive === false && status === "active" ? "Not armed" : status ?? "Checking status";
  const isBeneficiary = principal !== "owner";
  const showBottomNav = !isPublic && authed && !isBeneficiary && isOwnerRoute;

  return (
      <div className="app-layout min-h-screen lg:flex">
      {/* Desktop sidebar */}
      <aside className="app-sidebar hidden w-64 shrink-0 flex-col border-r border-border bg-bg p-5 lg:flex">
        <Link href={isBeneficiary ? "/recovery" : "/home"} className="brand-lockup flex items-center gap-2.5 text-base font-semibold tracking-tight">
          <span className="brand-mark"><VaultIcon className="h-4 w-4" /></span>
          <span>LegacyLock</span>
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
        <div className="sidebar-session mt-auto flex flex-col gap-2 border-t border-border pt-4">
          <StatusChip tone={unlocked ? "success" : "neutral"}>
            {vaultInitialized === false ? <VaultIcon className="h-3 w-3" /> : unlocked ? <LockOpen className="h-3 w-3" /> : <Lock className="h-3 w-3" />}
            {vaultInitialized === false ? "Vault not set up" : unlocked ? "Vault unlocked" : "Vault locked"}
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

      <div className="app-main min-w-0 flex-1 pb-20 lg:pb-0">
        {/* Topbar */}
        <header className="app-topbar sticky top-0 z-40 flex h-16 items-center gap-3 border-b border-border bg-bg px-4 lg:px-5">
          <Link href={isBeneficiary ? "/recovery" : "/home"} className="flex items-center gap-2 text-base font-semibold tracking-tight lg:hidden">
            <span className="brand-mark"><VaultIcon className="h-4 w-4" /></span>
            LegacyLock
          </Link>
          {principal === "owner" && (
            <div className="hidden lg:block">
              <StatusChip tone={statusTone} pulse={status === "grace"}>
                {statusLabel.toUpperCase()}
              </StatusChip>
            </div>
          )}
          <div className="ml-auto hidden items-center gap-2 lg:flex">
            <ThemeToggle theme={theme} onToggle={toggleTheme} />
            {principal === "owner" && recoveryReady === true && (
              <button type="button" className="btn-ghost !rounded-xl px-3 py-1.5 text-xs" disabled={status === "triggered"} onClick={onCheckin}>
                Check in
              </button>
            )}
            {vaultInitialized !== false && <VaultLockIndicator
              unlocked={unlocked}
              recoveryReady={recoveryReady}
              heartbeatActive={heartbeatActive}
              onLock={lock}
            />}
          </div>
          <div className="relative ml-auto lg:hidden">
            <button
              type="button"
              className="btn-ghost h-10 w-10 !p-0"
              aria-label={mobileMenuOpen ? "Close account menu" : "Open account menu"}
              aria-expanded={mobileMenuOpen}
              aria-controls="mobile-account-menu"
              onClick={() => setMobileMenuOpen((open) => !open)}
            >
              {mobileMenuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>
            {mobileMenuOpen && (
              <div id="mobile-account-menu" className="absolute right-0 top-12 z-50 flex w-64 flex-col gap-2 rounded-xl border border-border bg-surface p-3 shadow-vault">
                {principal === "owner" && (
                  <>
                    <StatusChip tone={statusTone}>{statusLabel.toLowerCase()}</StatusChip>
                    <p className="text-xs text-muted">{vaultInitialized === false ? "Vault not set up" : unlocked ? "Vault unlocked in this tab" : "Vault locked in this tab"}</p>
                    {unlocked && <button type="button" className="btn-ghost w-full justify-start" onClick={() => { lock(); setMobileMenuOpen(false); }}>Lock vault</button>}
                    <Link className="btn-ghost w-full justify-start" href="/settings/security" onClick={() => setMobileMenuOpen(false)}>Recovery readiness</Link>
                    <Link className="btn-ghost w-full justify-start" href="/settings" onClick={() => setMobileMenuOpen(false)}>Settings</Link>
                  </>
                )}
                <ThemeToggle theme={theme} onToggle={toggleTheme} />
                <button type="button" className="btn-ghost w-full justify-start" onClick={onLogout}>
                  <LogOut className="h-4 w-4" /> Log out
                </button>
              </div>
            )}
          </div>
        </header>

        <div id="app-content">{children}</div>

        {/* Mobile bottom navigation */}
        {showBottomNav && (
          <nav
            className="mobile-nav fixed inset-x-0 bottom-0 z-40 border-t border-border bg-bg lg:hidden"
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
                      "flex flex-col items-center justify-center gap-1 py-2 text-xs transition-colors",
                      active ? "font-medium text-text" : "text-muted",
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
