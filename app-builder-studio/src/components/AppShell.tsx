import { Link, useRouterState } from "@tanstack/react-router";
import type { ReactNode } from "react";

export function AppShell({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  const path = useRouterState({ select: (s) => s.location.pathname });
  const width = wide ? "max-w-[1120px]" : "max-w-[960px]";

  return (
    <div className="min-h-screen">
      <header className="no-print border-b bg-surface">
        <div className={`mx-auto flex h-14 items-center justify-between px-4 md:px-6 ${width}`}>
          <Link to="/" className="flex items-baseline gap-2">
            <span className="text-[17px] font-semibold tracking-tight">HypeKyte</span>
            <span className="hidden text-[13px] text-ink-3 sm:inline">Business verification</span>
          </Link>
          <nav className="flex items-center gap-1 text-[14px]">
            <Link to="/" className={`rounded-md px-3 py-1.5 ${path === "/" ? "text-ink" : "text-ink-2 hover:text-ink"}`}>
              Verifications
            </Link>
            <Link to="/verify" search={{}} className="rounded-md bg-ink px-3 py-1.5 font-medium text-surface hover:bg-ink/85">
              New verification
            </Link>
          </nav>
        </div>
      </header>
      <main className={`mx-auto w-full px-4 py-8 md:px-6 md:py-10 ${width}`}>{children}</main>
    </div>
  );
}

export function SectionTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-3">
      <h2 className="text-[16px] font-semibold">{children}</h2>
      {aside && <span className="text-[13px] text-ink-3">{aside}</span>}
    </div>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-lg border bg-surface ${className}`}>{children}</div>;
}
