"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { enforceLockDeadline, isUnlocked, lockVault, millisecondsUntilVaultLock, noteVaultActivity, noteVaultVisibility, subscribe } from "../crypto-session";

interface VaultContextValue {
  unlocked: boolean;
  lock: () => void;
}

// In-memory only — the raw VMK lives solely inside lib/crypto-session.ts and
// is never exposed to components, storage, cookies, or URLs.
const VaultContext = createContext<VaultContextValue>({
  unlocked: false,
  lock: () => {},
});

export function VaultProvider({ children }: { children: React.ReactNode }) {
  const [unlocked, setUnlocked] = useState(isUnlocked());

  useEffect(() => subscribe(() => setUnlocked(isUnlocked())), []);

  const lock = useCallback(() => {
    lockVault();
  }, []);

  // Timers are a prompt lock; crypto-session enforces elapsed deadlines even
  // when a browser suspends timers or restores a page from its back/forward cache.
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const schedule = () => {
      if (timer) clearTimeout(timer);
      const remaining = millisecondsUntilVaultLock();
      timer = remaining === null ? null : setTimeout(() => {
        enforceLockDeadline();
        schedule();
      }, remaining);
    };
    const onActivity = () => {
      noteVaultActivity();
      schedule();
    };
    window.addEventListener("pointerdown", onActivity);
    window.addEventListener("keydown", onActivity);
    const onVisibility = () => {
      noteVaultVisibility(document.hidden);
      schedule();
    };
    const onReturn = () => { enforceLockDeadline(); schedule(); };
    const onUnload = () => lockVault();
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("focus", onReturn);
    window.addEventListener("pageshow", onReturn);
    window.addEventListener("beforeunload", onUnload);
    const unsubscribe = subscribe(schedule);
    schedule();
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("focus", onReturn);
      window.removeEventListener("pageshow", onReturn);
      window.removeEventListener("beforeunload", onUnload);
      if (timer) clearTimeout(timer);
      unsubscribe();
      window.removeEventListener("pointerdown", onActivity);
      window.removeEventListener("keydown", onActivity);
    };
  }, []);

  return (
    <VaultContext.Provider value={{ unlocked, lock }}>
      {children}
    </VaultContext.Provider>
  );
}

export function useVault() {
  return useContext(VaultContext);
}
