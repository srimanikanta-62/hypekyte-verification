import { createFileRoute, Link } from "@tanstack/react-router";
import { queryOptions, useQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { AppShell, Card } from "@/components/AppShell";
import { StatusBadge } from "@/components/marks";
import { api, type Status } from "@/lib/api";

const listQuery = queryOptions({ queryKey: ["verifications"], queryFn: api.verifications, refetchOnWindowFocus: true });

export const Route = createFileRoute("/")({
  head: () => ({ meta: [{ title: "Verifications · HypeKyte" }] }),
  ssr: false,
  component: Verifications,
});

const STEPS = [
  { t: "Find the business", d: "From your location or a Google Maps search." },
  { t: "Check the registers", d: "GST registration and the Google listing, compared with each other." },
  { t: "Verify the phone", d: "A code sent to a number already on record for the business." },
];

function Verifications() {
  const { data, isLoading, error } = useQuery(listQuery);
  const items = data?.items ?? [];
  const count = (s: Status) => items.filter((i) => i.status === s).length;

  return (
    <AppShell>
      <div>
        <h1 className="text-[28px] font-semibold tracking-tight">Verifications</h1>
        <p className="mt-1 text-[15px] text-ink-2">Check that a business is real and that the person registering it belongs to it.</p>
      </div>

      <div className="mt-6 grid gap-3 sm:grid-cols-3">
        {STEPS.map((s, i) => (
          <div key={s.t} className="flex gap-3 rounded-lg border bg-surface p-4">
            <span className="tabular grid h-6 w-6 shrink-0 place-items-center rounded-full bg-page text-[12px] text-ink-2">{i + 1}</span>
            <div>
              <div className="text-[14px] font-medium">{s.t}</div>
              <div className="text-[13px] text-ink-2">{s.d}</div>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-10 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-[16px] font-semibold">History</h2>
        {items.length > 0 && (
          <div className="flex gap-4 text-[13px] text-ink-3">
            <span>{items.length} total</span>
            <span>{count("VERIFIED")} verified</span>
            <span>{count("NEEDS_REVIEW")} need review</span>
            <span>{count("UNVERIFIED")} unverified</span>
          </div>
        )}
      </div>

      <Card className="mt-3 overflow-hidden">
        {isLoading && <div className="h-32 animate-pulse bg-page" />}
        {error && (
          <p className="p-5 text-[14px] text-ink-2">
            Can't reach the verification server. Start the backend with <code className="rounded bg-page px-1.5 py-0.5 text-[13px]">uvicorn main:app --port 8000</code>.
          </p>
        )}
        {!isLoading && !error && items.length === 0 && (
          <div className="p-8 text-center">
            <p className="text-[15px] font-medium">No verifications yet</p>
            <p className="mt-1 text-[14px] text-ink-2">Completed verifications will appear here.</p>
          </div>
        )}
        {items.length > 0 && (
          <ul className="divide-y">
            {items.map((v) => (
              <li key={v.id}>
                <Link to="/case/$id" params={{ id: String(v.id) }} className="flex items-center gap-4 px-4 py-3.5 hover:bg-page">
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[15px]">{v.business_name}</span>
                    <span className="tabular block truncate text-[13px] text-ink-3">
                      {[v.business_category, v.gstin ?? "No GSTIN", v.phone_masked ? `+91 ${v.phone_masked}` : null].filter(Boolean).join(" · ")}
                    </span>
                  </span>
                  <span className="tabular hidden w-14 text-right text-[14px] text-ink-2 sm:block">{v.score}/100</span>
                  <span className="w-[112px] text-right">
                    <StatusBadge status={v.status} />
                  </span>
                  <ChevronRight className="h-4 w-4 shrink-0 text-ink-3" />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </AppShell>
  );
}
