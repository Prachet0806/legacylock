import { Vault as VaultIcon } from "lucide-react";

function Placeholder({ className = "" }: { className?: string }) {
  return <span aria-hidden="true" className={`block rounded-md bg-raised motion-safe:animate-pulse ${className}`} />;
}

export function HomeLoading({ message = "Opening your vault…" }: { message?: string }) {
  return (
    <div className="min-h-screen bg-bg" role="status" aria-live="polite" aria-busy="true">
      <div className="border-b border-border px-5 py-4">
        <div className="mx-auto flex max-w-5xl items-center gap-2.5">
          <span className="brand-mark"><VaultIcon className="h-4 w-4" /></span>
          <span className="font-semibold tracking-tight">LegacyLock</span>
        </div>
      </div>
      <main className="mx-auto max-w-5xl px-4 py-8 sm:py-10">
        <p className="text-sm text-muted">{message}</p>
        <div aria-hidden="true" className="mt-8">
          <Placeholder className="h-3 w-24" />
          <Placeholder className="mt-3 h-8 w-40" />
          <div className="surface-hero mt-6">
            <Placeholder className="h-3 w-24" />
            <Placeholder className="mt-4 h-6 w-48" />
            <div className="mt-8 border-t border-border pt-6">
              <Placeholder className="h-3 w-28" />
              <Placeholder className="mt-4 h-10 w-56 max-w-full" />
            </div>
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            {[0, 1, 2].map((item) => (
              <div className="stat-tile" key={item}>
                <Placeholder className="h-8 w-12" />
                <Placeholder className="h-3 w-24" />
              </div>
            ))}
          </div>
        </div>
      </main>
    </div>
  );
}
