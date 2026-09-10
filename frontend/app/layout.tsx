import type { Metadata } from "next";
import type { ReactNode } from "react";
import { VaultProvider } from "../lib/store/vault-context";
import { ToastProvider } from "../components/toast";
import { AppShell } from "../components/shell";
import "./globals.css";

export const metadata: Metadata = {
  title: "LegacyLock",
  description: "Zero-knowledge digital legacy vault",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" data-theme="dark">
      <body className="m-0 font-sans antialiased">
        <VaultProvider>
          <ToastProvider>
            <AppShell>{children}</AppShell>
          </ToastProvider>
        </VaultProvider>
      </body>
    </html>
  );
}
