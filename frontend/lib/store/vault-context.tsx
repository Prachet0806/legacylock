"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { isUnlocked, lockVault, subscribe } from "../crypto-session";

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

  // Lock policy (documented): hiding the tab starts a 5-minute grace timer;
  // returning cancels it. Closing/reloading wipes immediately via beforeunload.
  // Rationale: instant lock on Alt-Tab punishes legitimate multitasking, while
  // an unattended visible vault is the actual unattended-device threat.
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const onVisibility = () => {
      if (document.hidden) {
        timer = setTimeout(lockVault, 5 * 60 * 1000);
      } else if (timer) {
        clearTimeout(timer);
        timer = null;
      }
    };
    const onUnload = () => lockVault();
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("beforeunload", onUnload);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("beforeunload", onUnload);
      if (timer) clearTimeout(timer);
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
