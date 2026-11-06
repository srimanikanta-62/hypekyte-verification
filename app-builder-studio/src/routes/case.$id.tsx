import { createFileRoute, Link } from "@tanstack/react-router";
import { queryOptions, useSuspenseQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { AppShell, Card, SectionTitle } from "@/components/AppShell";
import { Glyph, Meter, ModeTag, Score, StatusBadge } from "@/components/marks";
import { api, type Signal } from "@/lib/api";
import { notify } from "@/lib/toast";

const caseQuery = (id: string) => queryOptions({ queryKey: ["case", id], queryFn: () => api.verification(id) });

export const Route = createFileRoute("/case/$id")({
  head: () => ({ meta: [{ title: "Verification result · HypeKyte" }] }),
  ssr: false,
  loader: ({ context, params }) => context.queryClient.ensureQueryData(caseQuery(params.id)),
  errorComponent: () => (
    <AppShell>
      <p className="text-[20px] font-semibold">Verification not found.</p>
      <Link to="/" className="mt-3 inline-block text-[14px] text-ink-2 underline">Back to verifications</Link>
    </AppShell>
  ),
  component: Result,
});

const GROUPS = [
  { id: "existence", title: "Does the business exist?" },
  { id: "consistency", title: "Do the details match?" },
  { id: "association", title: "Is the applicant linked to it?" },
] as const;

function Result() {
  const { id } = Route.useParams();
  const { data } = useSuspenseQuery(caseQuery(id));
  const r = data.result;
  const sub = r.submission;
  const filed = new Date(data.created_at.replace(" ", "T") + "Z");
  const simulatedUsed = r.signals.some((s) => s.mode === "simulated" || s.mode === "sandbox");

  return (
    <AppShell>
      <div className="no-print mb-6 flex flex-wrap items-center justify-between gap-3 text-[14px]">
        <Link to="/" className="inline-flex items-center gap-1.5 text-ink-2 hover:text-ink">
          <ArrowLeft className="h-4 w-4" /> Verifications
        </Link>
        <div className="flex gap-4 text-ink-2">
          <button onClick={() => navigator.clipboard.writeText(window.location.href).then(() => notify.ok("Link copied"))} className="hover:text-ink">
            Copy link
          </button>
          <button onClick={() => window.print()} className="hover:text-ink">
            Print
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="text-[13px] text-ink-3">
            Verification #{data.id} · {filed.toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}
          </div>
          <h1 className="mt-1 text-[30px] font-semibold leading-tight tracking-tight">{sub.business_name}</h1>
          <p className="mt-1 text-[14px] text-ink-2">{[sub.category, sub.address].filter(Boolean).join(" · ") || "No address on file"}</p>
          <p className="tabular mt-0.5 text-[13px] text-ink-3">
            {sub.gstin ? `GSTIN ${sub.gstin}` : "No GSTIN"} · {sub.phone_masked ? `Phone +91 ${sub.phone_masked}` : "Phone not verified"}
          </p>
        </div>
        <StatusBadge status={r.status} size="lg" />
      </div>

      <div className="mt-6 grid gap-4 md:grid-cols-[minmax(0,1fr)_280px]">
        <Card className="p-5">
          <div className="text-[13px] text-ink-3">Summary</div>
          <p className="mt-1 text-[17px] leading-snug">{r.headline}</p>
          {r.caps.length > 1 && (
            <ul className="mt-3 space-y-1 text-[14px] text-ink-2">
              {r.caps.slice(1).map((c) => (
                <li key={c}>• {c}</li>
              ))}
            </ul>
          )}
        </Card>
        <Card className="p-5">
          <div className="text-[13px] text-ink-3">Score</div>
          <Score value={r.score} className="mt-1 block text-[34px]" />
          <div className="mt-4 space-y-3">
            <Meter label="Business exists" value={r.existence} max={r.thresholds.existence_max} threshold={r.thresholds.existence} />
            <Meter label="Applicant linked" value={r.association} max={r.thresholds.association_max} threshold={r.thresholds.association} />
          </div>
          {r.deductions.length > 0 && (
            <ul className="mt-4 space-y-1 border-t pt-3 text-[13px]">
              {r.deductions.map((d) => (
                <li key={d.reason} className="flex gap-2">
                  <span className="tabular w-7 shrink-0 text-fail">−{d.points}</span>
                  <span className="text-ink-2">{d.reason}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
      <p className="mt-2 text-[12px] text-ink-3">
        To be verified, "Business exists" needs at least {r.thresholds.existence} and "Applicant linked" at least {r.thresholds.association}, with no unresolved issues.
      </p>

      <section className="mt-10">
        <SectionTitle aside={`${r.signals.length} checks`}>Checks</SectionTitle>
        <div className="space-y-6">
          {GROUPS.map((g) => {
            const items = r.signals.filter((s) => s.group === g.id);
            if (!items.length) return null;
            return (
              <div key={g.id}>
                <div className="mb-2 text-[14px] text-ink-2">{g.title}</div>
                <Card className="divide-y">
                  {items.map((s) => (
                    <CheckRow key={s.id} s={s} />
                  ))}
                </Card>
              </div>
            );
          })}
        </div>
      </section>

      {r.ledger.length > 0 && (
        <section className="mt-10">
          <SectionTitle>Comparison</SectionTitle>
          <Card className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-[14px]">
              <thead className="text-[12px] text-ink-3">
                <tr className="border-b">
                  <th className="px-4 py-2.5 font-normal">Field</th>
                  <th className="px-4 py-2.5 font-normal">Applicant</th>
                  <th className="px-4 py-2.5 font-normal">GST register</th>
                  <th className="px-4 py-2.5 font-normal">Google Maps</th>
                  <th className="px-4 py-2.5 font-normal">Result</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {r.ledger.map((row) => (
                  <tr key={row.field} className="align-top">
                    <td className="px-4 py-3 text-ink-2">{row.field}</td>
                    <td className="px-4 py-3">{row.submitted ?? <Dash />}</td>
                    <td className="px-4 py-3">{row.gst ?? <Dash />}</td>
                    <td className="px-4 py-3">{row.google ?? <Dash />}</td>
                    <td className={`px-4 py-3 text-[13px] ${row.note === "differs" ? "text-fail" : row.note === "match" || row.note === "OTP verified" ? "text-pass" : "text-ink-3"}`}>{row.note ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </section>
      )}

      {sub.similar.length > 0 && (
        <section className="mt-10">
          <SectionTitle>Similar listings nearby</SectionTitle>
          <div className="grid gap-2 sm:grid-cols-2">
            {sub.similar.map((s) => (
              <Card key={s.place_id} className="px-4 py-3">
                <div className="text-[14px] font-medium">{s.name}</div>
                <div className="text-[13px] text-ink-3">
                  {s.distance_m < 1000 ? `${s.distance_m} m` : `${(s.distance_m / 1000).toFixed(1)} km`} away · {s.same_pin ? "same PIN code" : "different PIN code"}
                </div>
              </Card>
            ))}
          </div>
        </section>
      )}

      <footer className="mt-12 border-t pt-4 text-[13px] leading-relaxed text-ink-3">
        <p>
          Data sources: Google Places API and gstinapi.in (live). OTP delivery and, for real GSTINs, the GST-registered mobile number are simulated
          in this prototype; those checks are labelled "Simulated".{simulatedUsed && " This result includes simulated or test data."}
        </p>
        <p className="mt-1">A GST registration or Google listing shows that a business exists. The applicant link comes from proving control of a phone number on record for the business.</p>
      </footer>
    </AppShell>
  );
}

function CheckRow({ s }: { s: Signal }) {
  return (
    <div className="flex gap-3 px-4 py-3">
      <Glyph outcome={s.outcome} className="mt-0.5" />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="text-[14px] font-medium">{s.label}</span>
          <span className="text-[12px] text-ink-3">{s.source}</span>
          {s.mode && s.mode !== "live" && <ModeTag mode={s.mode} />}
        </div>
        <p className="mt-0.5 text-[13px] leading-snug text-ink-2">{s.detail}</p>
      </div>
      <span className={`tabular shrink-0 text-[13px] ${s.points > 0 ? "text-ink" : s.points < 0 ? "text-fail" : "text-ink-3"}`}>
        {s.points > 0 ? `+${s.points}` : s.points < 0 ? s.points : ""}
      </span>
    </div>
  );
}

function Dash() {
  return <span className="text-ink-3">—</span>;
}
