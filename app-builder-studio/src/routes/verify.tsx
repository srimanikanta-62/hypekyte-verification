import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { ArrowRight, ChevronRight, ExternalLink, MapPin, Search } from "lucide-react";
import { AppShell, Card } from "@/components/AppShell";
import { DigitBoxes, GstinField, PlaceSearch } from "@/components/inputs";
import { Glyph, Meter, ModeTag, Score, StatusBadge } from "@/components/marks";
import { VirtualPhone } from "@/components/VirtualPhone";
import { api, ApiError, type NearbyPlace, type PhoneSource, type Session } from "@/lib/api";
import { notify } from "@/lib/toast";

type Step = "locate" | "identify" | "registry" | "phone" | "code" | "link" | "file";

export const Route = createFileRoute("/verify")({
  validateSearch: (search: Record<string, unknown>): { s?: string } => (typeof search["s"] === "string" ? { s: search["s"] } : {}),
  head: () => ({ meta: [{ title: "New verification · HypeKyte" }] }),
  ssr: false,
  component: VerifyPage,
});

const CATEGORIES = ["Restaurant", "Café", "Retail Store", "Event Organizer", "Hotel", "Other"];
const STORAGE_KEY = "hk.case.session";

const STEP_TITLES: Record<Step, string> = {
  locate: "Location",
  identify: "Business",
  registry: "GST",
  phone: "Phone",
  code: "Code",
  link: "Google listing",
  file: "Submit",
};

/* =================================================================== session hook */
function useCase(initialId?: string) {
  const [session, setSession] = useState<Session | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const navigate = useNavigate({ from: "/verify" });

  const adopt = useCallback((s: Session) => {
    setSession(s);
    try {
      localStorage.setItem(STORAGE_KEY, s.id);
    } catch {
      /* private mode */
    }
  }, []);

  const start = useCallback(async () => {
    const { session: s } = await api.start();
    adopt(s);
    navigate({ search: { s: s.id }, replace: true });
    return s;
  }, [adopt, navigate]);

  useEffect(() => {
    let id = initialId;
    if (!id) {
      try {
        id = localStorage.getItem(STORAGE_KEY) ?? undefined;
      } catch {
        id = undefined;
      }
    }
    (async () => {
      if (id) {
        try {
          const res = await api.session(id);
          if (!res.verification_id) {
            adopt(res.session);
            navigate({ search: { s: id }, replace: true });
            if (!initialId) notify.note("Continuing where you left off", "Your unfinished verification was restored.");
            return;
          }
        } catch {
          /* expired: start fresh */
        }
      }
      await start().catch((e) => notify.error(e));
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** Run an API call; keep the session in sync even when it fails; rethrow errors. */
  const run = useCallback(
    async <T extends { session?: Session }>(label: string, fn: () => Promise<T>): Promise<T> => {
      setBusy(label);
      try {
        const out = await fn();
        if (out.session) adopt(out.session);
        return out;
      } catch (e) {
        if (e instanceof ApiError && e.session) adopt(e.session);
        throw e;
      } finally {
        setBusy(null);
      }
    },
    [adopt],
  );

  const reset = useCallback(async () => {
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
    setSession(null);
    return start();
  }, [start]);

  return { session, busy, run, reset };
}

function initialStep(s: Session): Step {
  if (!s.presence) return "locate";
  if (!s.place && !s.not_on_google && !s.business_name) return "identify";
  if (!s.gst && !s.phone) return "registry";
  if (s.gst && s.gst.record && s.gst.confirmed === null) return "registry";
  if (!s.phone?.matched) return "phone";
  if (!s.otp?.verified) return "code";
  return "file";
}

/* ======================================================================== page */
function VerifyPage() {
  const { s: sid } = Route.useSearch();
  const { session, busy, run, reset } = useCase(sid);
  const [step, setStep] = useState<Step | null>(null);
  const [visited, setVisited] = useState<Set<Step>>(new Set());
  const [nearby, setNearby] = useState<NearbyPlace[] | null>(null);
  const [otpCode, setOtpCode] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    if (session && !step) setStep(initialStep(session));
  }, [session, step]);

  useEffect(() => {
    if (step) setVisited((v) => new Set(v).add(step));
  }, [step]);

  const go = (next: Step) => {
    setStep(next);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const fileCase = async () => {
    if (!session) return;
    try {
      const out = await run("Submitting…", () => api.finalize(session.id) as Promise<{ session?: Session; verification_id: number }>);
      try {
        localStorage.removeItem(STORAGE_KEY);
      } catch {
        /* ignore */
      }
      navigate({ to: "/case/$id", params: { id: String(out.verification_id) } });
    } catch (e) {
      notify.error(e);
    }
  };

  if (!session || !step) {
    return (
      <AppShell wide>
        <div className="h-40 animate-pulse rounded-lg bg-line/60" />
      </AppShell>
    );
  }

  const ctx: StepProps = { session, busy, run, go, nearby, setNearby, otpCode, setOtpCode, fileCase };
  const restart = () =>
    reset().then((s) => {
      setStep(initialStep(s));
      setVisited(new Set());
      setNearby(null);
    });

  return (
    <AppShell wide>
      <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_248px]">
        <section className="min-w-0">
          <Stepper session={session} step={step} visited={visited} onJump={go} />
          <div key={step} className="mt-8 max-w-[600px] animate-fade">
            {step === "locate" && <LocateStep {...ctx} />}
            {step === "identify" && <IdentifyStep {...ctx} />}
            {step === "registry" && <RegistryStep {...ctx} />}
            {step === "phone" && <PhoneStep {...ctx} />}
            {step === "code" && <CodeStep {...ctx} />}
            {step === "link" && <LinkStep {...ctx} />}
            {step === "file" && <FileStep {...ctx} />}
          </div>
          {busy && <p className="mt-6 text-[13px] text-ink-3">{busy}</p>}
        </section>

        <aside className="space-y-6 lg:sticky lg:top-6 lg:self-start">
          <Progress session={session} onFile={step !== "file" ? fileCase : undefined} onReset={restart} />
          <VirtualPhone
            sessionId={session.id}
            listening={step === "code" || step === "phone"}
            onCode={(c) => {
              setOtpCode(c);
              if (step !== "code" && session.phone?.matched) go("code");
            }}
          />
        </aside>
      </div>
    </AppShell>
  );
}

type StepProps = {
  session: Session;
  busy: string | null;
  run: <T extends { session?: Session }>(label: string, fn: () => Promise<T>) => Promise<T>;
  go: (s: Step) => void;
  nearby: NearbyPlace[] | null;
  setNearby: (n: NearbyPlace[] | null) => void;
  otpCode: string;
  setOtpCode: (c: string) => void;
  fileCase: () => void;
};

/* ===================================================================== stepper */
function Stepper({ session, step, visited, onJump }: { session: Session; step: Step; visited: Set<Step>; onJump: (s: Step) => void }) {
  const showLink = step === "link" || session.place_source === "gst_link";
  const steps: Step[] = ["locate", "identify", "registry", "phone", "code", ...(showLink ? (["link"] as Step[]) : []), "file"];
  const done: Record<Step, boolean> = {
    locate: !!session.presence,
    identify: !!(session.place || session.not_on_google || session.business_name),
    registry: !!(session.gst?.confirmed || (visited.has("phone") && !session.gst?.record)),
    phone: !!session.phone?.matched,
    code: !!session.otp?.verified,
    link: session.place_source === "gst_link",
    file: false,
  };
  const index = steps.indexOf(step);

  return (
    <nav aria-label="Progress">
      <div className="text-[13px] text-ink-3 sm:hidden">
        Step {index + 1} of {steps.length} · {STEP_TITLES[step]}
      </div>
      <div className="mt-2 flex gap-1 sm:hidden">
        {steps.map((s, i) => (
          <span key={s} className={`h-1 flex-1 rounded-full ${i <= index ? "bg-ink" : "bg-line"}`} />
        ))}
      </div>
      <ol className="hidden flex-wrap items-center gap-x-1 gap-y-2 text-[14px] sm:flex">
        {steps.map((s, i) => {
          const current = s === step;
          const reachable = (visited.has(s) || done[s]) && !current;
          return (
            <li key={s} className="flex items-center gap-1">
              <button
                disabled={!reachable}
                onClick={() => onJump(s)}
                className={`flex items-center gap-2 rounded-md px-2 py-1 ${current ? "font-medium text-ink" : done[s] ? "text-ink-2 hover:text-ink" : "text-ink-3"} disabled:cursor-default`}
              >
                <span
                  className={`tabular grid h-5 w-5 place-items-center rounded-full text-[11px] ${
                    current ? "bg-ink text-surface" : done[s] ? "bg-line text-ink" : "border border-line-2 text-ink-3"
                  }`}
                >
                  {done[s] && !current ? "✓" : i + 1}
                </span>
                {STEP_TITLES[s]}
              </button>
              {i < steps.length - 1 && <ChevronRight className="h-3.5 w-3.5 text-line-2" />}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

function Progress({ session, onFile, onReset }: { session: Session; onFile?: (() => void) | undefined; onReset: () => void }) {
  const p = session.preview;
  const canFile = !!(session.place || session.not_on_google || session.business_name || session.gst);
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between">
        <span className="text-[13px] text-ink-2">Current result</span>
        <StatusBadge status={p.status} />
      </div>
      <Score value={p.score} className="mt-3 block text-[30px]" />
      <div className="mt-4 space-y-3">
        <Meter label="Business exists" value={p.existence} max={60} threshold={20} hint="GST register and Google listing" />
        <Meter label="Applicant linked" value={p.association} max={40} threshold={30} hint="OTP on a phone number on record, on-site check" />
      </div>
      <p className="mt-4 text-[13px] leading-snug text-ink-2">{p.headline}</p>
      <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1 border-t pt-3 text-[13px]">
        {canFile && onFile && (
          <button onClick={onFile} className="text-ink-2 hover:text-ink">
            Submit now
          </button>
        )}
        <button onClick={onReset} className="text-ink-3 hover:text-ink">
          Start over
        </button>
      </div>
    </Card>
  );
}

/* ================================================================= step chrome */
function StepHead({ title, children }: { title: ReactNode; children?: ReactNode }) {
  return (
    <header className="mb-6">
      <h1 className="text-[26px] font-semibold leading-tight tracking-tight sm:text-[30px]">{title}</h1>
      {children && <p className="mt-2 text-[15px] leading-relaxed text-ink-2">{children}</p>}
    </header>
  );
}

function Choice({ title, note, onClick, disabled, icon }: { title: string; note: string; onClick: () => void; disabled?: boolean; icon?: ReactNode }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="group flex w-full items-center gap-4 rounded-lg border bg-surface p-4 text-left transition-colors hover:border-ink disabled:opacity-50"
    >
      {icon && <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-page text-ink-2">{icon}</span>}
      <span className="min-w-0 flex-1">
        <span className="block text-[15px] font-medium">{title}</span>
        <span className="block text-[13px] text-ink-2">{note}</span>
      </span>
      <ArrowRight className="h-4 w-4 text-ink-3 transition-transform group-hover:translate-x-0.5 group-hover:text-ink" />
    </button>
  );
}

function Primary({ children, onClick, disabled }: { children: ReactNode; onClick: () => void; disabled?: boolean }) {
  return (
    <button onClick={onClick} disabled={disabled} className="inline-flex items-center gap-2 rounded-md bg-ink px-4 py-2.5 text-[14px] font-medium text-surface hover:bg-ink/85 disabled:opacity-40">
      {children}
    </button>
  );
}

function Quiet({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return (
    <button onClick={onClick} className="text-[14px] text-ink-2 underline decoration-line-2 underline-offset-4 hover:text-ink hover:decoration-ink">
      {children}
    </button>
  );
}

function Hotkeys({ map }: { map: Record<string, () => void> }) {
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.tagName === "INPUT" || t.tagName === "TEXTAREA") return;
      map[e.key]?.();
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [map]);
  return null;
}

/* ==================================================================== locate */
function LocateStep({ session, run, go, setNearby }: StepProps) {
  const [locating, setLocating] = useState(false);

  const remote = async () => {
    try {
      await run("Saving…", () => api.presence(session.id, { at_business: false }));
      setNearby(null);
      go("identify");
    } catch (e) {
      notify.error(e);
    }
  };

  const here = () => {
    if (!("geolocation" in navigator)) {
      notify.note("Location not available", "Search for your business instead.");
      void remote();
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        setLocating(false);
        try {
          const { coords } = pos;
          const out = await run("Looking for businesses near you…", () =>
            api.presence(session.id, { at_business: true, lat: coords.latitude, lng: coords.longitude, accuracy: coords.accuracy }),
          );
          setNearby(out.nearby);
          if (!out.precise) notify.note("Location is approximate", `Accurate to about ${Math.round(coords.accuracy)} m, so it won't count as being on-site.`);
          go("identify");
        } catch (e) {
          notify.error(e);
        }
      },
      (err) => {
        setLocating(false);
        notify.note(err.code === 1 ? "Location permission denied" : "Couldn't get your location", "You can search for the business instead.");
        remote();
      },
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 30000 },
    );
  };

  return (
    <div>
      <StepHead title="Are you at the business right now?">If so, we can find it from your location instead of you searching for it.</StepHead>
      <div className="grid gap-3">
        <Choice icon={<MapPin className="h-4 w-4" />} title={locating ? "Getting your location…" : "Yes, I'm there"} note="We only keep the distance, not your exact location." onClick={here} disabled={locating} />
        <Choice icon={<Search className="h-4 w-4" />} title="No, I'm somewhere else" note="Search for the business by name." onClick={remote} disabled={locating} />
      </div>
      <Hotkeys map={{ "1": here, "2": remote }} />
    </div>
  );
}

/* ================================================================== identify */
function IdentifyStep({ session, run, go, nearby }: StepProps) {
  const [typed, setTyped] = useState(session.name_source === "typed" ? session.business_name ?? "" : "");
  const place = session.place;

  const pick = async (place_id: string, token: string | null, source: "nearby" | "search") => {
    try {
      await run("Loading the Google listing…", () => api.place(session.id, place_id, token, source));
    } catch (e) {
      notify.error(e);
    }
  };

  const nameOnly = async () => {
    if (typed.trim().length < 2) return notify.note("Business name needed", "Type the name of your business first.");
    try {
      await run("Saving…", () => api.profile(session.id, { business_name: typed.trim() }));
      go("registry");
    } catch (e) {
      notify.error(e);
    }
  };

  return (
    <div>
      <StepHead title={place ? "Is this your business?" : "Find your business"}>
        {place ? "This is what Google Maps has. We'll compare it with the GST register and your phone." : "Search by name and pick it from Google Maps. The address, category and phone are filled in from the listing."}
      </StepHead>

      {!place && nearby && nearby.length > 0 && (
        <div className="mb-6">
          <div className="mb-2 text-[13px] text-ink-2">Businesses near you</div>
          <Card className="divide-y overflow-hidden">
            {nearby.slice(0, 8).map((n) => (
              <button key={n.place_id} onClick={() => pick(n.place_id, null, "nearby")} className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-page">
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-2">
                    <span className="truncate text-[15px]">{n.name}</span>
                    {n.name_match && <span className="shrink-0 rounded-full bg-pass-bg px-1.5 text-[11px] leading-[18px] text-pass">Name match</span>}
                  </span>
                  <span className="block truncate text-[13px] text-ink-3">{[n.type_label, n.short_address].filter(Boolean).join(" · ")}</span>
                </span>
                <span className="tabular shrink-0 text-[13px] text-ink-3">{n.distance_m < 1000 ? `${n.distance_m} m` : `${(n.distance_m / 1000).toFixed(1)} km`}</span>
              </button>
            ))}
          </Card>
          <div className="mb-2 mt-6 text-[13px] text-ink-2">Not in the list?</div>
        </div>
      )}

      {!place && (
        <PlaceSearch
          sessionId={session.id}
          initial={typed}
          placeholder="Search business name"
          onTyped={setTyped}
          autoFocus={!nearby?.length}
          onPick={(s, token) => pick(s.place_id, token, "search")}
          footer={(text) => (
            <div className="mt-4">
              <Quiet onClick={nameOnly}>{text.trim().length >= 2 ? `Not on Google Maps? Continue as “${text.trim()}”` : "Not on Google Maps?"}</Quiet>
            </div>
          )}
        />
      )}

      {place && <ListingCard session={session} run={run} />}

      {place && (
        <div className="mt-6 flex flex-wrap items-center gap-5">
          <Primary onClick={() => go("registry")}>Yes, that's us</Primary>
          <Quiet onClick={() => run("Clearing…", () => api.clearPlace(session.id)).catch((e) => notify.error(e))}>Not this one</Quiet>
        </div>
      )}
    </div>
  );
}

function ListingCard({ session, run }: { session: Session; run: StepProps["run"] }) {
  const place = session.place!;
  const lookalikes = session.similar.filter((s) => s.is_lookalike);
  const setCategory = (category: string) => run("Saving…", () => api.profile(session.id, { category })).catch((e) => notify.error(e));

  return (
    <Card className="overflow-hidden">
      <div className="p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-[19px] font-semibold leading-snug">{place.name}</div>
            <div className="mt-1 text-[14px] text-ink-2">{place.address}</div>
          </div>
          <span className="shrink-0 text-[12px] text-ink-3">Google Maps</span>
        </div>
        <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 text-[14px] sm:grid-cols-3">
          <Field k="Type" v={place.type_label ?? place.primary_type ?? "—"} />
          <Field k="Status" v={place.business_status === "OPERATIONAL" ? "Open" : (place.business_status ?? "—").replaceAll("_", " ").toLowerCase()} warn={place.business_status !== "OPERATIONAL"} />
          <Field k="Reviews" v={place.rating ? `${place.rating} ★ (${place.rating_count.toLocaleString("en-IN")})` : String(place.rating_count)} />
          <Field k="PIN code" v={place.pincode ?? "—"} />
          <Field k="Phone" v={place.phone.listed ? (place.phone.sms_capable ? `${place.phone.hint?.masked} (mobile)` : `${place.phone.display} (landline)`) : "Not listed"} />
          {place.maps_uri && (
            <div>
              <dt className="text-[12px] text-ink-3">Map</dt>
              <dd>
                <a href={place.maps_uri} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 hover:underline">
                  Open <ExternalLink className="h-3 w-3" />
                </a>
              </dd>
            </div>
          )}
        </dl>
      </div>
      <div className="border-t px-5 py-4">
        <div className="mb-2 text-[12px] text-ink-3">Category{session.category_source === "inferred" && " (from the listing, tap to change)"}</div>
        <div className="flex flex-wrap gap-1.5">
          {CATEGORIES.map((c) => (
            <button
              key={c}
              onClick={() => setCategory(c)}
              className={`rounded-full border px-3 py-1 text-[13px] transition-colors ${session.category === c ? "border-ink bg-ink text-surface" : "hover:border-ink"}`}
            >
              {c}
            </button>
          ))}
        </div>
      </div>
      {lookalikes.length > 0 && (
        <div className="border-t bg-warn-bg px-5 py-3 text-[13px] text-warn">
          {lookalikes.length} similar listing{lookalikes.length > 1 ? "s" : ""} nearby ({lookalikes.map((l) => l.name).slice(0, 2).join(", ")}). The phone check will confirm which one is yours.
        </div>
      )}
    </Card>
  );
}

function Field({ k, v, warn }: { k: string; v: string; warn?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="text-[12px] text-ink-3">{k}</dt>
      <dd className={`truncate ${warn ? "text-fail" : ""}`}>{v}</dd>
    </div>
  );
}

/* ================================================================== registry */
function RegistryStep({ session, run, go, busy }: StepProps) {
  const gst = session.gst;
  const [mode, setMode] = useState<"ask" | "enter" | "address">(gst ? "enter" : "ask");
  const [shake, setShake] = useState(0);
  const [entryKey, setEntryKey] = useState(0);

  const noGstin = async () => {
    try {
      if (session.gst) await run("Removing GSTIN…", () => api.removeGstin(session.id));
      if (!session.place && !session.not_on_google) setMode("address");
      else go("phone");
    } catch (e) {
      notify.error(e);
    }
  };

  const submit = useCallback(
    async (value: string) => {
      try {
        await run("Checking the GST register…", () => api.gstin(session.id, value));
      } catch (e) {
        setShake((k) => k + 1);
        if (e instanceof ApiError && e.code === "GSTIN_NOT_FOUND") {
          notify.error(e, { label: session.place ? "Continue without" : "Use Google Maps", onClick: () => (session.place ? go("phone") : go("identify")) });
        } else notify.error(e);
      }
    },
    [run, session.id, session.place, go],
  );

  const confirm = async (yes: boolean) => {
    try {
      await run(yes ? "Loading registered contact…" : "Okay…", () => api.confirmGstin(session.id, yes));
      if (yes) {
        notify.ok("GST registration confirmed");
        go("phone");
      } else setEntryKey((k) => k + 1);
    } catch (e) {
      notify.error(e);
    }
  };

  if (mode === "address") {
    return (
      <div>
        <StepHead title="Where is the business?">Without a GSTIN or a Google listing, we need the address.</StepHead>
        <PlaceSearch
          sessionId={session.id}
          kind="address"
          placeholder="Search address"
          onPick={async (s) => {
            try {
              await run("Saving address…", () => api.notOnGoogle(session.id, [s.main, s.secondary].filter(Boolean).join(", ")));
              go("phone");
            } catch (e) {
              notify.error(e);
            }
          }}
        />
        <div className="mt-4">
          <Quiet onClick={() => setMode("ask")}>I have a GSTIN</Quiet>
        </div>
      </div>
    );
  }

  if (mode === "ask") {
    return (
      <div>
        <StepHead title="Do you have a GSTIN?">A GST registration is the strongest proof that a business exists. It's optional.</StepHead>
        <div className="grid gap-3">
          <Choice title="Yes, I have a GSTIN" note="Paste or type it. It's checked as you type." onClick={() => setMode("enter")} />
          <Choice title="No GSTIN" note={session.place ? "We'll use your Google listing and phone." : "We'll ask for the address instead."} onClick={noGstin} />
        </div>
        <Hotkeys map={{ "1": () => setMode("enter"), "2": noGstin }} />
      </div>
    );
  }

  const record = gst?.record;
  const showCard = record && gst?.confirmed !== false;

  return (
    <div>
      <StepHead title={showCard ? "Is this your GST registration?" : "Enter your GSTIN"}>
        {showCard ? "If it's yours, we'll use the mobile number registered with GST to verify you." : "15 characters. It's checked automatically once complete."}
      </StepHead>

      {!showCard && (
        <div>
          <GstinField key={entryKey} initial={gst?.confirmed === false ? "" : gst?.gstin ?? ""} onSubmit={submit} busy={!!busy} shakeKey={shake} />
          <div className="mt-5 flex flex-wrap gap-x-5 gap-y-2">
            <Quiet onClick={noGstin}>I don't have a GSTIN</Quiet>
            <Quiet onClick={() => submit("00AAAAA0000A1ZT")}>Use the test GSTIN</Quiet>
          </div>
        </div>
      )}

      {showCard && <GstCard session={session} />}

      {showCard && (
        <div className="mt-6 flex flex-wrap items-center gap-5">
          <Primary onClick={() => confirm(true)}>{record!.status.toLowerCase() === "active" ? "Yes, that's us" : "It's ours, continue"}</Primary>
          <Quiet onClick={() => confirm(false)}>No, wrong GSTIN</Quiet>
          {!session.place && <Quiet onClick={() => go("identify")}>Verify another way</Quiet>}
        </div>
      )}
    </div>
  );
}

function GstCard({ session }: { session: Session }) {
  const gst = session.gst!;
  const r = gst.record!;
  const active = r.status.toLowerCase() === "active";
  const mark = (name: string | null) => {
    if (!name) return "—";
    const words = gst.highlight?.[name] ?? [];
    return name.split(" ").map((w, i) => (
      <span key={i} className={words.includes(w) ? "rounded-sm bg-mark" : ""}>
        {w}{" "}
      </span>
    ));
  };
  return (
    <Card className="p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[19px] font-semibold leading-snug">{mark(r.trade_name || r.legal_name)}</div>
          {r.trade_name && r.legal_name && r.trade_name !== r.legal_name && <div className="mt-0.5 text-[14px] text-ink-2">{mark(r.legal_name)}</div>}
          <div className="tabular mt-1 text-[13px] tracking-wide text-ink-3">{r.gstin}</div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1.5">
          <span className={`rounded-full px-2 py-0.5 text-[12px] font-medium ${active ? "bg-pass-bg text-pass" : "bg-fail-bg text-fail"}`}>{r.status}</span>
          <span className="flex gap-1">
            {r.cached && <ModeTag mode="cached" />}
            {r.mode !== "live" && <ModeTag mode={r.mode} />}
          </span>
        </div>
      </div>
      <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 text-[14px] sm:grid-cols-3">
        <Field k="Registered" v={r.registration_date ?? "—"} />
        <Field k="Taxpayer type" v={r.taxpayer_type ?? "—"} />
        <Field k="Holder" v={gst.decoded.holder_type ?? "—"} />
        <Field k="State" v={r.state ?? gst.decoded.state ?? "—"} />
        <Field k="City" v={r.city ?? "—"} />
        <Field k="PIN code" v={r.pincode ?? "—"} />
      </dl>
      {r.address && <p className="mt-4 border-t pt-3 text-[14px] text-ink-2">{r.address}</p>}
      {gst.name_score !== null && session.business_name && (
        <p className="mt-3 text-[13px] text-ink-2">
          Name match with “{session.business_name}”:{" "}
          <span className={`font-medium ${gst.name_score >= 85 ? "text-pass" : gst.name_score >= 75 ? "text-warn" : "text-fail"}`}>{gst.name_score}%</span>
        </p>
      )}
      {r.test && <p className="mt-3 rounded-md bg-warn-bg px-3 py-2 text-[13px] text-warn">This is the provider's test record. It shows the integration works but isn't evidence about a real business.</p>}
    </Card>
  );
}

/* ===================================================================== phone */
const STRENGTH: Record<PhoneSource, string> = { gst: "Strongest", places: "Strong", self: "Weak" };

function PhoneStep({ session, run, go }: StepProps) {
  const targets = session.phone_targets;
  const usable = targets.filter((t) => t.sms_capable && !t.exhausted);
  const current = session.phone?.source ?? null;
  const [digits, setDigits] = useState("");
  const [shake, setShake] = useState(0);
  const autoPicked = useRef(false);

  const choose = useCallback(
    async (source: PhoneSource) => {
      setDigits("");
      try {
        await run("…", () => api.phoneTarget(session.id, source));
      } catch (e) {
        notify.error(e);
      }
    },
    [run, session.id],
  );

  useEffect(() => {
    if (!current && !autoPicked.current && usable[0]) {
      autoPicked.current = true;
      choose(usable[0].source);
    }
  }, [current, usable, choose]);

  const target = targets.find((t) => t.source === current);
  const nextOption = usable.find((t) => t.source !== current);

  const claim = async (value: string) => {
    try {
      await run("Sending code…", () => api.claimPhone(session.id, value));
      go("code");
    } catch (e) {
      setShake((k) => k + 1);
      setDigits("");
      if (e instanceof ApiError && e.code === "PHONE_ATTEMPTS_EXCEEDED" && nextOption) {
        notify.error(e, { label: "Use another number", onClick: () => choose(nextOption.source) });
      } else notify.error(e);
    }
  };

  return (
    <div>
      <StepHead title="Verify the business phone">
        We send a code only to a number that's already on record for this business. Fill in the hidden digits to show you know it.
      </StepHead>

      <Card className="mb-7 divide-y overflow-hidden">
        {targets.map((t) => {
          const disabled = !t.sms_capable || t.exhausted;
          const on = t.source === current;
          return (
            <button key={t.source} disabled={disabled} onClick={() => choose(t.source)} className={`flex w-full items-center gap-3 px-4 py-3 text-left ${on ? "bg-page" : "hover:bg-page/60"} disabled:cursor-not-allowed disabled:opacity-45`}>
              <span className={`grid h-4 w-4 shrink-0 place-items-center rounded-full border ${on ? "border-ink" : "border-line-2"}`}>{on && <span className="h-2 w-2 rounded-full bg-ink" />}</span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-2 text-[15px]">
                  {t.label}
                  {t.mode && t.mode !== "live" && <ModeTag mode={t.mode} />}
                </span>
                <span className="tabular block text-[13px] text-ink-3">
                  {t.hint ? `+91 ${t.hint.masked}` : t.display ? t.display : "Any 10-digit mobile"}
                  {!t.sms_capable && " · landline, can't receive SMS"}
                  {t.exhausted && " · no attempts left"}
                </span>
              </span>
              <span className="shrink-0 text-right text-[12px] text-ink-3">{STRENGTH[t.source]}</span>
            </button>
          );
        })}
      </Card>

      {target && (
        <div key={target.source} className="animate-fade">
          <p className="mb-3 text-[14px] text-ink-2">{target.hint ? `Enter the ${target.hint.hidden} missing digits` : "Your 10-digit mobile number"}</p>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[18px] text-ink-3">+91</span>
            {target.hint ? (
              <DigitBoxes key={target.source} label="Missing digits" length={target.hint.hidden} prefix={target.hint.prefix} suffix={target.hint.suffix} value={digits} onChange={setDigits} onComplete={claim} autoFocus shakeKey={shake} />
            ) : (
              <DigitBoxes key="self" label="Mobile number" length={10} value={digits} onChange={setDigits} onComplete={claim} autoFocus shakeKey={shake} />
            )}
          </div>
          {target.source === "self" && <p className="mt-3 text-[13px] text-ink-3">A personal number shows you're reachable, but not that you belong to the business, so the result will need a manual review.</p>}
          {session.phone_failures[target.source] ? <p className="mt-3 text-[13px] text-fail">{3 - (session.phone_failures[target.source] ?? 0)} attempts left for this number.</p> : null}
        </div>
      )}
    </div>
  );
}

/* ====================================================================== code */
function CodeStep({ session, run, go, otpCode, setOtpCode }: StepProps) {
  const [shake, setShake] = useState(0);
  const [now, setNow] = useState(Date.now() / 1000);
  const submitting = useRef(false);

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now() / 1000), 500);
    return () => clearInterval(t);
  }, []);

  const nextStep = (s: Session): Step => (s.gst?.confirmed && !s.place && !s.not_on_google ? "link" : "file");

  const verify = useCallback(
    async (code: string) => {
      if (submitting.current) return;
      submitting.current = true;
      try {
        const out = await run("Checking code…", () => api.verifyOtp(session.id, code));
        notify.ok("Phone verified");
        go(nextStep(out.session));
      } catch (e) {
        setShake((k) => k + 1);
        setOtpCode("");
        notify.error(e);
      } finally {
        submitting.current = false;
      }
    },
    [run, session.id, go, setOtpCode],
  );

  useEffect(() => {
    if (otpCode.length === 4) verify(otpCode);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [otpCode]);

  const resendIn = Math.max(0, Math.ceil((session.otp?.resend_at ?? 0) - now));
  const expiresIn = Math.max(0, Math.ceil((session.otp?.expires_at ?? 0) - now));

  if (session.otp?.verified) {
    return (
      <div>
        <StepHead title="Phone verified">You confirmed {session.phone?.hint?.masked ? `+91 ${session.phone.hint.masked}` : "the number"}.</StepHead>
        <Primary onClick={() => go(nextStep(session))}>Continue</Primary>
      </div>
    );
  }

  return (
    <div>
      <StepHead title="Enter the 4-digit code">
        Sent to <span className="tabular text-ink">+91 {session.phone?.hint?.masked}</span>. In this demo it appears on the phone on the right.
      </StepHead>
      <DigitBoxes label="One-time code" otp length={4} value={otpCode} onChange={setOtpCode} autoFocus shakeKey={shake} />
      <div className="mt-5 flex flex-wrap items-center gap-5 text-[14px]">
        <span className="tabular text-ink-3">
          {expiresIn > 0 ? `Expires in ${Math.floor(expiresIn / 60)}:${String(expiresIn % 60).padStart(2, "0")}` : <span className="text-fail">Code expired</span>}
        </span>
        {resendIn > 0 ? (
          <span className="tabular text-ink-3">Resend in {resendIn}s</span>
        ) : (
          <Quiet onClick={() => run("Resending…", () => api.resendOtp(session.id)).then(() => notify.ok("New code sent")).catch((e) => notify.error(e))}>Resend code</Quiet>
        )}
        <Quiet onClick={() => go("phone")}>Use another number</Quiet>
      </div>
    </div>
  );
}

/* ====================================================================== link */
function LinkStep({ session, run, go }: StepProps) {
  const r = session.gst?.record;
  const initial = [r?.trade_name || r?.legal_name, r?.city].filter(Boolean).join(" ");
  return (
    <div>
      <StepHead title="Is it on Google Maps too?">Optional. Linking the listing lets us compare it with your GST address, which strengthens the result.</StepHead>
      {!session.place ? (
        <PlaceSearch sessionId={session.id} initial={initial} placeholder="Search business name" onPick={(s, token) => run("Loading the listing…", () => api.place(session.id, s.place_id, token, "gst_link")).catch((e) => notify.error(e))} />
      ) : (
        <ListingCard session={session} run={run} />
      )}
      <div className="mt-6 flex flex-wrap items-center gap-5">
        {session.place && <Primary onClick={() => go("file")}>Continue</Primary>}
        {session.place && <Quiet onClick={() => run("Clearing…", () => api.clearPlace(session.id)).catch((e) => notify.error(e))}>Not this one</Quiet>}
        {!session.place && <Quiet onClick={() => go("file")}>Skip</Quiet>}
      </div>
    </div>
  );
}

/* ====================================================================== file */
function FileStep({ session, fileCase, busy }: StepProps) {
  const p = session.preview;
  const groups = [
    { id: "existence", title: "Business exists" },
    { id: "consistency", title: "Details match" },
    { id: "association", title: "Applicant linked" },
  ] as const;
  return (
    <div>
      <StepHead title="Review and submit">This is the result based on what we've checked. Submitting saves it with all the details.</StepHead>
      <Card className="p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <StatusBadge status={p.status} size="lg" />
          <Score value={p.score} className="text-[26px]" />
        </div>
        <p className="mt-3 text-[14px] text-ink-2">{p.headline}</p>
      </Card>
      <div className="mt-6 grid gap-6 sm:grid-cols-3">
        {groups.map((g) => (
          <div key={g.id}>
            <div className="mb-2 text-[13px] font-medium">{g.title}</div>
            <ul className="space-y-2">
              {p.signals.filter((s) => s.group === g.id).map((s) => (
                <li key={s.id} className="flex items-center gap-2 text-[13px]">
                  <Glyph outcome={s.outcome} />
                  <span className="min-w-0 flex-1 truncate text-ink-2">{s.label}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="mt-8">
        <Primary onClick={fileCase} disabled={!!busy}>
          Submit
        </Primary>
      </div>
    </div>
  );
}
