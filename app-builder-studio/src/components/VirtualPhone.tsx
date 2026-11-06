import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

type Msg = { id: string; to: string; sender: string; body: string; at: number };

function codeOf(body: string) {
  return body.match(/\b(\d{4,6})\b/)?.[1] ?? null;
}

function ago(at: number) {
  const s = Math.max(0, Math.round(Date.now() / 1000 - at));
  return s < 45 ? "now" : `${Math.round(s / 60)} min`;
}

/**
 * Demo phone. With OTP_MODE=simulated the backend writes the "SMS" to a per-session inbox
 * instead of sending it; this panel polls that inbox so the flow can be tried end to end.
 */
export function VirtualPhone({ sessionId, listening, onCode }: { sessionId: string | null; listening: boolean; onCode: (code: string) => void }) {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [buzzKey, setBuzzKey] = useState(0);
  const [banner, setBanner] = useState<Msg | null>(null);
  const seen = useRef<Set<string>>(new Set());
  const first = useRef(true);

  useEffect(() => {
    seen.current = new Set();
    first.current = true;
    setMessages([]);
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) return;
    let stop = false;
    const tick = async () => {
      try {
        const { messages: inbox } = await api.inbox(sessionId);
        if (stop) return;
        const fresh = inbox.filter((m) => !seen.current.has(m.id));
        inbox.forEach((m) => seen.current.add(m.id));
        setMessages(inbox.slice().reverse());
        if (fresh.length && !first.current) {
          setBuzzKey((k) => k + 1);
          setBanner(fresh[fresh.length - 1] ?? null);
          navigator.vibrate?.(100);
        }
        first.current = false;
      } catch {
        /* backend offline: the page shows its own error */
      }
    };
    tick();
    const t = setInterval(tick, listening ? 1200 : 4000);
    return () => {
      stop = true;
      clearInterval(t);
    };
  }, [sessionId, listening]);

  useEffect(() => {
    if (!banner) return;
    const t = setTimeout(() => setBanner(null), 9000);
    return () => clearTimeout(t);
  }, [banner]);

  const fill = (m: Msg) => {
    const code = codeOf(m.body);
    if (code) onCode(code);
    setBanner(null);
  };

  return (
    <>
      <div className="hidden lg:block">
        <div key={buzzKey} className={`mx-auto w-[232px] ${buzzKey ? "animate-buzz" : ""}`}>
          <div className="rounded-[30px] border-[6px] border-ink bg-surface">
            <div className="flex h-[400px] flex-col overflow-hidden rounded-[24px]">
              <div className="flex justify-center pt-2">
                <span className="h-[14px] w-[64px] rounded-full bg-ink" />
              </div>
              <div className="border-b px-4 pb-2.5 pt-3 text-center text-[13px] font-medium">Messages</div>
              <div className="flex-1 space-y-2 overflow-hidden p-3">
                {messages.length === 0 && (
                  <p className="pt-10 text-center text-[12px] text-ink-3">{listening ? "Waiting for the code…" : "No messages"}</p>
                )}
                {messages.slice(0, 4).map((m, i) => (
                  <button
                    key={m.id}
                    onClick={() => fill(m)}
                    className={`block w-full rounded-xl bg-page px-3 py-2 text-left transition-colors hover:bg-line ${i === 0 && buzzKey ? "animate-slide-down" : ""} ${i > 0 ? "opacity-50" : ""}`}
                  >
                    <div className="flex justify-between text-[11px] text-ink-3">
                      <span>{m.sender}</span>
                      <span>{ago(m.at)}</span>
                    </div>
                    <p className="mt-0.5 text-[12.5px] leading-snug text-ink">
                      <Highlight body={m.body} />
                    </p>
                    {i === 0 && <p className="mt-1 text-[11px] font-medium text-ink-2">Tap to fill</p>}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
        <p className="mx-auto mt-3 max-w-[232px] text-center text-[12px] leading-snug text-ink-3">
          Demo phone. Codes are shown here instead of being sent by SMS.
        </p>
      </div>

      {banner && (
        <button
          onClick={() => fill(banner)}
          className="fixed inset-x-3 top-3 z-50 animate-slide-down rounded-xl border bg-surface p-3 text-left shadow-[0_8px_24px_-8px_rgba(0,0,0,0.25)] lg:hidden"
        >
          <div className="flex justify-between text-[12px] text-ink-3">
            <span>{banner.sender} · demo SMS</span>
            <span>Tap to fill</span>
          </div>
          <p className="mt-0.5 text-[14px]">
            <Highlight body={banner.body} />
          </p>
        </button>
      )}
    </>
  );
}

function Highlight({ body }: { body: string }) {
  const code = codeOf(body);
  if (!code) return <>{body}</>;
  const [before, after] = body.split(code);
  return (
    <>
      {before}
      <b className="tabular font-semibold tracking-wide">{code}</b>
      {after}
    </>
  );
}
