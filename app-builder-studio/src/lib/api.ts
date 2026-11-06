// Typed client for the FastAPI backend (backend/main.py).
// Every mutating call returns the updated, server-masked session view, even on errors,
// so the UI never has to guess counters such as attempts left.

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://127.0.0.1:8000";

export type Status = "VERIFIED" | "NEEDS_REVIEW" | "UNVERIFIED";
export type Outcome = "pass" | "warn" | "fail" | "info" | "skip";
export type Mode = "live" | "sandbox" | "simulated" | "offline" | "cached" | null;
export type PhoneSource = "gst" | "places" | "self";

export interface PhoneHint {
  prefix: string;
  suffix: string;
  hidden: number;
  masked: string;
}

export interface Place {
  place_id: string;
  name: string;
  address: string;
  short_address: string;
  lat: number;
  lng: number;
  primary_type: string | null;
  type_label: string | null;
  types: string[];
  business_status: string | null;
  pincode: string | null;
  state: string | null;
  city: string | null;
  website: string | null;
  maps_uri: string | null;
  rating: number | null;
  rating_count: number;
  phone: { listed: boolean; hint: PhoneHint | null; sms_capable: boolean; display: string | null };
}

export interface GstRecord {
  gstin: string;
  legal_name: string | null;
  trade_name: string | null;
  status: string;
  taxpayer_type: string | null;
  constitution: string | null;
  registration_date: string | null;
  cancellation_date: string | null;
  state_code: string | null;
  state: string | null;
  address: string | null;
  city: string | null;
  pincode: string | null;
  nature_of_business: string[];
  test: boolean;
  mode: Mode;
  cached?: boolean;
}

export interface Decoded {
  state_code: string | null;
  state: string | null;
  pan: string | null;
  holder_type: string | null;
}

export interface SignalLite {
  id: string;
  group: "existence" | "association" | "consistency";
  label: string;
  outcome: Outcome;
  points: number;
  source: string;
}

export interface Signal extends SignalLite {
  detail: string;
  mode: Mode;
}

export interface PhoneTarget {
  source: PhoneSource;
  label: string;
  hint: PhoneHint | null;
  sms_capable: boolean;
  display?: string | null;
  mode: Mode;
  exhausted: boolean;
  points: number;
}

export interface Similar {
  place_id: string;
  name: string;
  short_address: string | null;
  distance_m: number;
  name_score: number;
  same_pin: boolean;
  is_lookalike: boolean;
}

export interface Session {
  id: string;
  business_name: string | null;
  name_source: "typed" | "listing" | null;
  category: string | null;
  category_source: "user" | "inferred" | null;
  presence: { at_business: boolean; precise?: boolean; accuracy?: number } | null;
  place: Place | null;
  place_source: "nearby" | "search" | "gst_link" | null;
  similar: Similar[];
  not_on_google: boolean;
  manual_address: string | null;
  gst: {
    gstin: string;
    decoded: Decoded;
    error: string | null;
    confirmed: boolean | null;
    record: GstRecord | null;
    highlight: Record<string, string[]> | null;
    name_score: number | null;
    contact: { found: boolean; mode: Mode; note: string | null } | null;
  } | null;
  phone_targets: PhoneTarget[];
  phone: { source: PhoneSource; matched: boolean; hint: PhoneHint | null } | null;
  phone_failures: Partial<Record<PhoneSource, number>>;
  otp: { sent: boolean; verified: boolean; expires_at: number; resend_at: number; attempts_left: number } | null;
  preview: {
    status: Status;
    score: number;
    existence: number;
    association: number;
    headline: string;
    caps: string[];
    signals: SignalLite[];
  };
  modes: { otp: string; gst_contact: string };
}

export interface NearbyPlace {
  place_id: string;
  name: string;
  short_address: string | null;
  type_label: string | null;
  primary_type: string | null;
  distance_m: number;
  name_match: boolean;
}

export interface Suggestion {
  place_id: string;
  main: string;
  secondary: string | null;
  types: string[];
}

export interface LedgerRow {
  field: string;
  submitted: string | null;
  gst: string | null;
  google: string | null;
  note: string | null;
}

export interface VerificationResult {
  status: Status;
  score: number;
  existence: number;
  association: number;
  penalty: number;
  deductions: { reason: string; points: number }[];
  headline: string;
  signals: Signal[];
  caps: string[];
  hard_fails: string[];
  ledger: LedgerRow[];
  thresholds: { existence: number; association: number; existence_max: number; association_max: number };
  submission: {
    business_name: string;
    category: string | null;
    address: string | null;
    gstin: string | null;
    place: Place | null;
    gst: Session["gst"];
    phone_masked: string | null;
    phone_source: PhoneSource | null;
    presence: Session["presence"];
    similar: Similar[];
    modes: Session["modes"];
  };
}

export interface VerificationRecord {
  id: number;
  session_id: string;
  business_name: string;
  business_category: string | null;
  address: string | null;
  gstin: string | null;
  place_id: string | null;
  phone_masked: string | null;
  status: Status;
  score: number;
  created_at: string;
  result: VerificationResult;
}

export type VerificationListItem = Omit<VerificationRecord, "result" | "session_id" | "address">;

export class ApiError extends Error {
  code: string;
  status: number;
  session?: Session | undefined;
  extra: Record<string, unknown>;

  constructor(status: number, body: Record<string, unknown>) {
    super(String(body["message"] ?? body["detail"] ?? `Request failed (${status})`));
    this.status = status;
    this.code = String(body["code"] ?? (status === 422 ? "VALIDATION" : "HTTP_ERROR"));
    if (body["session"]) this.session = body["session"] as Session;
    this.extra = body;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError(0, { code: "NETWORK", message: "Can't reach the verification server. Is the backend running?" });
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, body);
  return body as T;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, body === undefined ? { method: "POST" } : { method: "POST", body: JSON.stringify(body) });

type WithSession<T = object> = { session: Session } & T;

export const api = {
  meta: () => request<{ categories: string[]; otp_mode: string; gst_contact_mode: string; sandbox_gstin: string; otp_length: number }>("/api/meta"),
  start: (business_name?: string) => post<WithSession>("/api/sessions", business_name ? { business_name } : {}),
  session: (id: string) => request<WithSession<{ verification_id: number | null }>>(`/api/sessions/${id}`),
  profile: (id: string, body: { business_name?: string; category?: string }) => post<WithSession>(`/api/sessions/${id}/profile`, body),
  presence: (id: string, body: { at_business: boolean; lat?: number; lng?: number; accuracy?: number }) =>
    post<WithSession<{ nearby: NearbyPlace[]; precise?: boolean }>>(`/api/sessions/${id}/presence`, body),
  autocomplete: (q: string, token: string, sessionId?: string, kind: "business" | "address" = "business") =>
    request<{ suggestions: Suggestion[] }>(
      `/api/places/autocomplete?${new URLSearchParams({ q, token, kind, ...(sessionId ? { session_id: sessionId } : {}) })}`,
    ),
  place: (id: string, place_id: string, token: string | null, source: "nearby" | "search" | "gst_link") =>
    post<WithSession>(`/api/sessions/${id}/place`, { place_id, token, source }),
  clearPlace: (id: string) => request<WithSession>(`/api/sessions/${id}/place`, { method: "DELETE" }),
  notOnGoogle: (id: string, address: string) => post<WithSession>(`/api/sessions/${id}/not-on-google`, { address }),
  gstin: (id: string, gstin: string) => post<WithSession>(`/api/sessions/${id}/gstin`, { gstin }),
  removeGstin: (id: string) => request<WithSession>(`/api/sessions/${id}/gstin`, { method: "DELETE" }),
  confirmGstin: (id: string, confirmed: boolean) => post<WithSession>(`/api/sessions/${id}/gstin/confirm`, { confirmed }),
  phoneTarget: (id: string, source: PhoneSource) => post<WithSession>(`/api/sessions/${id}/phone/target`, { source }),
  claimPhone: (id: string, digits: string) =>
    post<WithSession<{ otp: { expires_in: number; resend_in: number; length: number } }>>(`/api/sessions/${id}/phone/claim`, { digits }),
  resendOtp: (id: string) => post<WithSession>(`/api/sessions/${id}/otp/resend`),
  verifyOtp: (id: string, code: string) => post<WithSession>(`/api/sessions/${id}/otp/verify`, { code }),
  inbox: (id: string) =>
    request<{ messages: { id: string; to: string; sender: string; body: string; at: number }[] }>(`/api/dev/sms/${id}`),
  finalize: (id: string) => post<{ verification_id: number; status: Status; score: number }>(`/api/sessions/${id}/finalize`),
  verifications: () => request<{ items: VerificationListItem[] }>("/api/verifications"),
  verification: (vid: number | string) => request<VerificationRecord>(`/api/verifications/${vid}`),
};
