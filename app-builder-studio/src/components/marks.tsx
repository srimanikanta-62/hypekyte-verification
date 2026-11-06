import { Check, Info, Minus, TriangleAlert, X } from "lucide-react";
import type { Mode, Outcome, Status } from "@/lib/api";

export const STATUS_LABEL: Record<Status, string> = {
  VERIFIED: "Verified",
  NEEDS_REVIEW: "Needs review",
  UNVERIFIED: "Unverified",
};

const STATUS_STYLE: Record<Status, string> = {
  VERIFIED: "bg-pass-bg text-pass",
  NEEDS_REVIEW: "bg-warn-bg text-warn",
  UNVERIFIED: "bg-fail-bg text-fail",
};

const DOT: Record<Status, string> = { VERIFIED: "bg-pass", NEEDS_REVIEW: "bg-warn", UNVERIFIED: "bg-fail" };

export function StatusBadge({ status, size = "sm" }: { status: Status; size?: "sm" | "lg" }) {
  const lg = size === "lg";
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full font-medium ${STATUS_STYLE[status]} ${lg ? "px-3 py-1 text-[14px]" : "px-2 py-0.5 text-[12px]"}`}>
      <span className={`rounded-full ${DOT[status]} ${lg ? "h-2 w-2" : "h-1.5 w-1.5"}`} />
      {STATUS_LABEL[status]}
    </span>
  );
}

const OUTCOME: Record<Outcome, { Icon: typeof Check; cls: string; label: string }> = {
  pass: { Icon: Check, cls: "bg-pass-bg text-pass", label: "Passed" },
  warn: { Icon: TriangleAlert, cls: "bg-warn-bg text-warn", label: "Warning" },
  fail: { Icon: X, cls: "bg-fail-bg text-fail", label: "Failed" },
  info: { Icon: Info, cls: "bg-page text-ink-2", label: "Note" },
  skip: { Icon: Minus, cls: "bg-page text-ink-3", label: "Not checked" },
};

export function Glyph({ outcome, className = "" }: { outcome: Outcome; className?: string }) {
  const { Icon, cls, label } = OUTCOME[outcome];
  return (
    <span title={label} className={`inline-grid h-5 w-5 shrink-0 place-items-center rounded-full ${cls} ${className}`}>
      <Icon className="h-3 w-3" strokeWidth={2.5} />
    </span>
  );
}

const MODE_LABEL: Record<string, string> = {
  live: "Live",
  sandbox: "Sandbox",
  simulated: "Simulated",
  cached: "Cached",
  offline: "Offline",
};

/** Where a piece of evidence came from. Only non-live sources are highlighted. */
export function ModeTag({ mode }: { mode: Mode | undefined }) {
  if (!mode) return null;
  const loud = mode === "simulated" || mode === "sandbox";
  return (
    <span className={`inline-block rounded-full px-1.5 text-[11px] leading-[18px] ${loud ? "bg-warn-bg text-warn" : "bg-page text-ink-3"}`}>
      {MODE_LABEL[mode] ?? mode}
    </span>
  );
}

export function Meter({ label, value, max, threshold, hint }: { label: string; value: number; max: number; threshold: number; hint?: string }) {
  const pct = Math.min(100, (value / max) * 100);
  return (
    <div title={hint}>
      <div className="flex items-baseline justify-between text-[13px]">
        <span className="text-ink-2">{label}</span>
        <span className="tabular text-ink">
          {value}
          <span className="text-ink-3"> / {max}</span>
        </span>
      </div>
      <div className="relative mt-1.5 h-1.5 rounded-full bg-line">
        <div className={`h-full rounded-full transition-[width] duration-500 ${value >= threshold ? "bg-ink" : "bg-ink-3"}`} style={{ width: `${pct}%` }} />
        <div className="absolute -top-1 h-3.5 w-px bg-ink-2" style={{ left: `${(threshold / max) * 100}%` }} title={`Needs ${threshold}`} />
      </div>
    </div>
  );
}

export function Score({ value, className = "" }: { value: number; className?: string }) {
  return (
    <span className={`tabular font-semibold leading-none tracking-tight ${className}`}>
      {value}
      <span className="font-normal text-ink-3">/100</span>
    </span>
  );
}
