import type { Metadata } from "next";
import type { ReactNode } from "react";
import { VaultProvider } from "../lib/store/vault-context";

export const metadata: Metadata = {
  title: "LegacyLock",
  description: "Zero-knowledge digital legacy vault",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body style={{ fontFamily: "sans-serif", margin: 0 }}>
        <VaultProvider>{children}</VaultProvider>
      </body>
    </html>
  );
}
