// Error / success toasts. Every backend error code maps to a short title and optional action.
import { toast as sonner } from "sonner";
import { ApiError } from "./api";

type Action = { label: string; onClick: () => void };
type Tone = "error" | "ok" | "note";

const TITLES: Record<string, string> = {
  GSTIN_INVALID_FORMAT: "Invalid GSTIN format",
  GSTIN_INVALID_CHECKSUM: "GSTIN check failed",
  GSTIN_NOT_FOUND: "GSTIN not registered",
  GSTIN_INACTIVE: "GST registration not active",
  PHONE_MISMATCH: "Number doesn't match",
  PHONE_ATTEMPTS_EXCEEDED: "Too many attempts",
  PHONE_NOT_SMS_CAPABLE: "Landline number",
  PHONE_INVALID: "Invalid mobile number",
  OTP_INVALID: "Wrong code",
  OTP_EXPIRED: "Code expired",
  OTP_ATTEMPTS_EXCEEDED: "Too many attempts",
  OTP_COOLDOWN: "Please wait",
  OTP_SEND_LIMIT: "Too many codes",
  PROVIDER_UNAVAILABLE: "Service unavailable",
  PROVIDER_TIMEOUT: "Service timed out",
  PROVIDER_CREDITS: "Out of credits",
  RATE_LIMITED: "Too many requests",
  NETWORK: "Can't reach the server",
  SESSION_NOT_FOUND: "Session expired",
};

const DOT: Record<Tone, string> = { error: "bg-fail", ok: "bg-pass", note: "bg-ink-3" };

function Body({ title, message, tone, action, id }: { title: string; message: string; tone: Tone; action?: Action | undefined; id?: string | number }) {
  return (
    <div className="flex items-start gap-3">
      <span className={`mt-[7px] h-2 w-2 shrink-0 rounded-full ${DOT[tone]}`} />
      <div className="min-w-0 flex-1">
        <div className="text-[14px] font-medium text-ink">{title}</div>
        {message && <p className="mt-0.5 text-[13px] leading-snug text-ink-2">{message}</p>}
      </div>
      {action && (
        <button
          onClick={() => {
            action.onClick();
            if (id !== undefined) sonner.dismiss(id);
          }}
          className="shrink-0 self-center rounded-md border px-2.5 py-1 text-[13px] font-medium hover:bg-page"
        >
          {action.label}
        </button>
      )}
    </div>
  );
}

function describe(err: unknown) {
  const e = err instanceof ApiError ? err : null;
  return {
    title: (e?.code && TITLES[e.code]) || "Something went wrong",
    message: e?.message || (err instanceof Error ? err.message : "Please try again."),
  };
}

export const notify = {
  error(err: unknown, action?: Action) {
    const { title, message } = describe(err);
    sonner.custom((id) => <Body title={title} message={message} tone="error" action={action} id={id} />, { duration: action ? 6000 : 4000 });
  },
  actionable(err: unknown, action: Action) {
    notify.error(err, action);
  },
  ok(title: string, message = "") {
    sonner.custom(() => <Body title={title} message={message} tone="ok" />, { duration: 2500 });
  },
  note(title: string, message: string) {
    sonner.custom(() => <Body title={title} message={message} tone="note" />, { duration: 4000 });
  },
};
