import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Check, Loader2, Search, X } from "lucide-react";
import { api, type Suggestion } from "@/lib/api";
import { checkGstin, cleanGstin, decodeGstin, firstProblem } from "@/lib/gstin";

/* ------------------------------------------------------------------ DigitBoxes
 * One real <input> (paste, SMS autofill and backspace work natively) over drawn boxes.
 * Optional prefix/suffix show the known digits of a masked phone number.
 */
export function DigitBoxes({
  length,
  value,
  onChange,
  onComplete,
  prefix,
  suffix,
  autoFocus,
  shakeKey,
  disabled,
  otp = false,
  label,
}: {
  length: number;
  value: string;
  onChange: (v: string) => void;
  onComplete?: (v: string) => void;
  prefix?: string;
  suffix?: string;
  autoFocus?: boolean;
  shakeKey?: number;
  disabled?: boolean;
  otp?: boolean;
  label: string;
}) {
  const ref = useRef<HTMLInputElement>(null);
  const [focused, setFocused] = useState(false);

  useEffect(() => {
    if (autoFocus) ref.current?.focus();
  }, [autoFocus]);

  const set = (raw: string) => {
    let digits = raw.replace(/\D/g, "");
    if (prefix && suffix && digits.length === prefix.length + length + suffix.length) {
      digits = digits.slice(prefix.length, prefix.length + length);
    }
    digits = digits.slice(0, length);
    onChange(digits);
    if (digits.length === length) onComplete?.(digits);
  };

  const fixed = (text: string) => <span className="tabular px-1 text-[22px] tracking-[0.18em] text-ink-3">{text}</span>;

  return (
    <div className="relative inline-block">
      <div key={shakeKey} className={`flex items-center gap-1.5 ${shakeKey ? "animate-shake" : ""}`} onClick={() => ref.current?.focus()}>
        {prefix && fixed(prefix)}
        {Array.from({ length }).map((_, i) => {
          const ch = value[i];
          const active = focused && i === Math.min(value.length, length - 1);
          return (
            <span
              key={i}
              className={`tabular grid h-12 w-10 place-items-center rounded-md border bg-surface text-[22px] transition-colors ${
                active ? "border-ink ring-1 ring-ink" : ch ? "border-line-2" : "border-line"
              }`}
            >
              {ch ?? ""}
            </span>
          );
        })}
        {suffix && fixed(suffix)}
      </div>
      <input
        ref={ref}
        aria-label={label}
        value={value}
        disabled={disabled}
        inputMode="numeric"
        autoComplete={otp ? "one-time-code" : "off"}
        onChange={(e) => set(e.target.value)}
        onPaste={(e) => {
          e.preventDefault();
          set(e.clipboardData.getData("text"));
        }}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        className="absolute inset-0 h-full w-full cursor-text opacity-0"
      />
    </div>
  );
}

/* ------------------------------------------------------------------ GstinField
 * Paste-friendly, decodes as you type, submits automatically at 15 characters.
 */
export function GstinField({ initial = "", onSubmit, busy, shakeKey }: { initial?: string; onSubmit: (gstin: string) => void; busy: boolean; shakeKey?: number }) {
  const [value, setValue] = useState(cleanGstin(initial));
  const submitted = useRef<string | null>(initial ? cleanGstin(initial) : null);
  const ref = useRef<HTMLInputElement>(null);
  const check = checkGstin(value);
  const decoded = decodeGstin(value);
  const problem = check === "bad-format" || (value.length > 0 && value.length < 15) ? firstProblem(value) : null;

  useEffect(() => {
    ref.current?.focus();
  }, []);

  useEffect(() => {
    if (value.length === 15 && submitted.current !== value && !busy) {
      submitted.current = value;
      onSubmit(value);
    }
  }, [value, busy, onSubmit]);

  const facts = [
    decoded.state && `${decoded.state}`,
    decoded.pan && `PAN ${decoded.pan}`,
    decoded.holder,
  ].filter(Boolean) as string[];

  return (
    <div>
      <div key={shakeKey} className={`flex items-center rounded-lg border bg-surface pr-3 focus-within:border-ink ${shakeKey ? "animate-shake" : ""}`}>
        <input
          ref={ref}
          aria-label="GSTIN"
          value={value}
          placeholder="22AAAAA0000A1Z5"
          spellCheck={false}
          autoCapitalize="characters"
          onChange={(e) => setValue(cleanGstin(e.target.value))}
          onKeyDown={(e) => {
            if (e.key === "Enter" && value.length === 15 && !busy) onSubmit(value);
          }}
          className="tabular min-w-0 flex-1 bg-transparent px-4 py-3 text-[20px] uppercase tracking-[0.12em] outline-none placeholder:normal-case placeholder:tracking-[0.12em] placeholder:text-ink-3/60"
        />
        {busy ? (
          <Loader2 className="h-4 w-4 animate-spin text-ink-3" />
        ) : value.length === 15 ? (
          check === "ok" ? <Check className="h-4 w-4 text-pass" /> : <X className="h-4 w-4 text-fail" />
        ) : (
          <span className="tabular text-[13px] text-ink-3">{value.length}/15</span>
        )}
      </div>
      <p className="mt-2 min-h-[20px] text-[13px] text-ink-2">
        {busy
          ? "Checking the GST register…"
          : value.length === 15 && check === "bad-checksum"
            ? <span className="text-fail">The last character doesn't match the rest, so one character is likely mistyped.</span>
            : [...facts, problem && `next: ${problem}`].filter(Boolean).join(" · ")}
      </p>
    </div>
  );
}

/* ----------------------------------------------------------------- PlaceSearch
 * The business-name field doubles as the Google Maps search.
 */
export function PlaceSearch({
  sessionId,
  initial = "",
  placeholder,
  kind = "business",
  onPick,
  onTyped,
  footer,
  autoFocus = true,
}: {
  sessionId: string | null;
  initial?: string;
  placeholder: string;
  kind?: "business" | "address";
  onPick: (s: Suggestion, token: string) => void;
  onTyped?: (text: string) => void;
  footer?: (text: string) => ReactNode;
  autoFocus?: boolean;
}) {
  const [text, setText] = useState(initial);
  const [items, setItems] = useState<Suggestion[]>([]);
  const [loading, setLoading] = useState(false);
  const [active, setActive] = useState(0);
  const [open, setOpen] = useState(false);
  const token = useMemo(() => crypto.randomUUID(), []);
  const ref = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (autoFocus) ref.current?.focus();
  }, [autoFocus]);

  useEffect(() => {
    onTyped?.(text);
    const q = text.trim();
    if (q.length < 2) {
      setItems([]);
      return;
    }
    setLoading(true);
    const t = setTimeout(async () => {
      try {
        const { suggestions } = await api.autocomplete(q, token, sessionId ?? undefined, kind);
        setItems(suggestions);
        setActive(0);
        setOpen(true);
      } catch {
        setItems([]);
      } finally {
        setLoading(false);
      }
    }, 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text]);

  const onKey = (e: KeyboardEvent) => {
    if (!items.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => (a + 1) % items.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => (a - 1 + items.length) % items.length);
    } else if (e.key === "Enter" && open) {
      e.preventDefault();
      const pick = items[active];
      if (pick) onPick(pick, token);
      setOpen(false);
    } else if (e.key === "Escape") setOpen(false);
  };

  return (
    <div className="relative">
      <div className="flex items-center gap-2.5 rounded-lg border bg-surface px-3.5 focus-within:border-ink">
        <Search className="h-4 w-4 shrink-0 text-ink-3" />
        <input
          ref={ref}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKey}
          onFocus={() => items.length && setOpen(true)}
          placeholder={placeholder}
          className="min-w-0 flex-1 bg-transparent py-3 text-[16px] outline-none placeholder:text-ink-3"
          role="combobox"
          aria-expanded={open}
          aria-controls="place-listbox"
          aria-autocomplete="list"
        />
        {loading && <Loader2 className="h-4 w-4 animate-spin text-ink-3" />}
      </div>

      {open && items.length > 0 && (
        <ul id="place-listbox" role="listbox" className="absolute inset-x-0 top-full z-20 mt-1.5 overflow-hidden rounded-lg border bg-surface shadow-[0_10px_30px_-12px_rgba(0,0,0,0.2)]">
          {items.map((s, i) => (
            <li key={s.place_id} role="option" aria-selected={i === active}>
              <button
                onMouseEnter={() => setActive(i)}
                onClick={() => {
                  onPick(s, token);
                  setOpen(false);
                }}
                className={`block w-full px-3.5 py-2.5 text-left ${i === active ? "bg-page" : ""}`}
              >
                <span className="block truncate text-[15px]">{s.main}</span>
                {s.secondary && <span className="block truncate text-[13px] text-ink-3">{s.secondary}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
      {footer?.(text)}
    </div>
  );
}
