"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { zeroMemory } from "../crypto";

interface VaultContextValue {
  vmk: Uint8Array | null;
  unlocked: boolean;
  setVMK: (raw: Uint8Array) => void;
  lock: () => void;
}

// In-memory only — never persist to localStorage/sessionStorage/cookies/URL.
const VaultContext = createContext<VaultContextValue>({
  vmk: null,
  unlocked: false,
  setVMK: () => {},
  lock: () => {},
});

export function VaultProvider({ children }: { children: React.ReactNode }) {
  const [vmk, setVmkState] = useState<Uint8Array | null>(null);
  const vmkRef = useRef<Uint8Array | null>(null);

  const setVMK = useCallback((raw: Uint8Array) => {
    if (vmkRef.current) zeroMemory(vmkRef.current);
    const copy = new Uint8Array(raw);
    vmkRef.current = copy;
    setVmkState(copy);
  }, []);

  const lock = useCallback(() => {
    if (vmkRef.current) zeroMemory(vmkRef.current);
    vmkRef.current = null;
    setVmkState(null);
  }, []);

  // Clear on tab close / refresh (vault requires re-unlock).
  useEffect(() => {
    const onUnload = () => {
      if (vmkRef.current) zeroMemory(vmkRef.current);
      vmkRef.current = null;
    };
    window.addEventListener("beforeunload", onUnload);
    return () => window.removeEventListener("beforeunload", onUnload);
  }, []);

  return (
    <VaultContext.Provider value={{ vmk, unlocked: vmk !== null, setVMK, lock }}>
      {children}
    </VaultContext.Provider>
  );
}

export function useVault() {
  return useContext(VaultContext);
}
