// Offline GSTIN decoding: everything a GSTIN reveals by itself, shown while the user types.

const BASE36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";
export const SANDBOX_GSTIN = "00AAAAA0000A1ZT";
export const GSTIN_PATTERN = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;

export const STATES: Record<string, string> = {
  "01": "Jammu & Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
  "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
  "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
  "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
  "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
  "26": "Dadra & Nagar Haveli and Daman & Diu", "27": "Maharashtra", "29": "Karnataka", "30": "Goa",
  "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
  "35": "Andaman & Nicobar", "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
  "97": "Other Territory", "00": "Sandbox (test)",
};

const HOLDERS: Record<string, string> = {
  C: "Company", P: "Individual / Proprietor", H: "HUF", F: "Firm / LLP", A: "AOP",
  T: "Trust", B: "BOI", L: "Local authority", J: "Juridical person", G: "Government",
};

export function cleanGstin(value: string) {
  return value.toUpperCase().replace(/[^0-9A-Z]/g, "").slice(0, 15);
}

export function checksumChar(g: string) {
  let total = 0;
  let factor = 2;
  for (let i = 13; i >= 0; i--) {
    const product = BASE36.indexOf(g[i] ?? "0") * factor;
    total += Math.floor(product / 36) + (product % 36);
    factor = factor === 2 ? 1 : 2;
  }
  return BASE36.charAt((36 - (total % 36)) % 36);
}

export type GstinCheck = "incomplete" | "bad-format" | "bad-checksum" | "ok";

export function checkGstin(g: string): GstinCheck {
  if (g.length < 15) return "incomplete";
  if (!GSTIN_PATTERN.test(g)) return "bad-format";
  if (g !== SANDBOX_GSTIN && checksumChar(g) !== g[14]) return "bad-checksum";
  return "ok";
}

export function decodeGstin(g: string) {
  const state = g.length >= 2 ? STATES[g.slice(0, 2)] ?? null : null;
  const pan = g.length >= 12 ? g.slice(2, 12) : null;
  const holder = g.length >= 6 ? HOLDERS[g.charAt(5)] ?? null : null;
  return { state, stateCode: g.slice(0, 2), pan, holder };
}

/** Where the typed value first breaks the GSTIN pattern (for inline guidance). */
export function firstProblem(g: string): string | null {
  const rules: [RegExp, string][] = [
    [/^[0-9]{0,2}$/, "starts with a 2-digit state code"],
    [/^[0-9]{2}[A-Z]{0,5}$/, "then 5 letters of the PAN"],
    [/^[0-9]{2}[A-Z]{5}[0-9]{0,4}$/, "then 4 digits"],
    [/^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]?$/, "then 1 letter"],
    [/^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]?$/, "then an entity number"],
    [/^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z?$/, "then the letter Z"],
    [/^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]?$/, "then a check character"],
  ];
  for (const [re, hint] of rules) if (re.test(g)) return g.length === 15 ? null : hint;
  return "doesn't follow the GSTIN pattern";
}
