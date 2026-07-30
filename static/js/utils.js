// Shared helpers used across views.

export async function api(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const r = await fetch(path, opts);
  const j = await r.json().catch(() => ({ success: false, error: "bad json" }));
  if (!r.ok || !j.success) throw new Error(j.error || `HTTP ${r.status}`);
  return j.data;
}

export const get  = (p)    => api("GET", p);
export const post = (p, b) => api("POST", p, b);
export const put  = (p, b) => api("PUT", p, b);
export const del  = (p)    => api("DELETE", p);

export function fmtMoney(n, opts = {}) {
  if (n == null || isNaN(n)) return "—";
  const abs = Math.abs(n);
  if (opts.compact && abs >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (opts.compact && abs >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
  if (opts.compact && abs >= 1e3) return `$${(n / 1e3).toFixed(2)}K`;
  return n.toLocaleString("en-US", {
    style: "currency", currency: "USD",
    minimumFractionDigits: opts.cents === false ? 0 : 2,
    maximumFractionDigits: opts.cents === false ? 0 : 2,
  });
}

export function fmtPct(n, digits = 2) {
  if (n == null || isNaN(n)) return "—";
  return `${n.toFixed(digits)}%`;
}

export function fmtNum(n, digits = 2) {
  if (n == null || isNaN(n)) return "—";
  return Number(n).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtInt(n) {
  if (n == null || isNaN(n)) return "—";
  return Math.round(n).toLocaleString("en-US");
}

export function fmtDate(s) {
  if (!s) return "—";
  return s.split("T")[0];
}

// Whole days between a YYYY-MM-DD (or ISO) date and today (local midnight).
// Returns null if unparseable. Positive = in the past.
export function daysSince(s) {
  if (!s) return null;
  const d = new Date(`${s.split("T")[0]}T00:00:00`);
  if (isNaN(d)) return null;
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((today - d) / 86400000);
}

// Human label for a days-since count: "today", "1 day ago", "12 days ago".
export function fmtDaysSince(s) {
  const n = daysSince(s);
  if (n == null) return "—";
  if (n <= 0) return "today";
  return `${n} day${n === 1 ? "" : "s"} ago`;
}

export function statusClass(status) {
  if (!status) return "";
  const s = status.toString().toLowerCase();
  if (s === "new" || s === "increased") return "text-green";
  if (s === "decreased" || s === "exited") return "text-red";
  return "text-muted";
}

export function decisionClass(decision) {
  if (decision === "TRADE") return "badge blue";
  if (decision === "INVEST") return "badge green";
  return "badge";
}

export function assessmentClass(a) {
  if (a === "UNDERVALUED") return "badge green";
  if (a === "OVERVALUED") return "badge red";
  if (a === "FAIR_VALUE") return "badge orange";
  return "badge";
}

// Sort an array of row objects by a key, ascending or descending.
// Nulls sort last regardless of direction. Numbers sort numerically; everything
// else falls back to locale string compare with numeric option.
export function sortRows(rows, key, dir) {
  if (!key || !Array.isArray(rows)) return rows;
  const mult = dir === "desc" ? -1 : 1;
  return [...rows].sort((a, b) => {
    const av = a == null ? null : a[key];
    const bv = b == null ? null : b[key];
    const aNull = av == null || av === "";
    const bNull = bv == null || bv === "";
    if (aNull && bNull) return 0;
    if (aNull) return 1;
    if (bNull) return -1;
    if (typeof av === "number" && typeof bv === "number") return (av - bv) * mult;
    const an = Number(av), bn = Number(bv);
    if (!isNaN(an) && !isNaN(bn)) return (an - bn) * mult;
    return String(av).localeCompare(String(bv), undefined, { numeric: true }) * mult;
  });
}

// Toggle a sort state object { key, dir } on a column click.
// First click sets asc; second click flips to desc; third resets dir to asc again.
export function toggleSortState(state, col) {
  if (state.key !== col) { state.key = col; state.dir = "asc"; return; }
  state.dir = state.dir === "asc" ? "desc" : "asc";
}

// Format a number as a whole-unit currency amount (no cents by default).
export function fmtCcy(n, ccy, digits = 0) {
  if (n == null || isNaN(n)) return "—";
  try {
    return Number(n).toLocaleString("en-US", {
      style: "currency", currency: ccy || "USD",
      minimumFractionDigits: digits, maximumFractionDigits: digits,
    });
  } catch (e) {
    return `${ccy} ${Math.round(Number(n)).toLocaleString()}`;
  }
}

// Look up a from→to FX rate in a { "AUD_USD": {rate}, ... } map, falling back to
// the inverse pair. Returns 1 for same-currency, null if unknown.
export function fxRate(rates, from, to) {
  from = (from || "USD").toUpperCase();
  to = (to || "USD").toUpperCase();
  if (from === to) return 1;
  const e = (rates || {})[`${from}_${to}`];
  if (e && e.rate) return Number(e.rate);
  const inv = (rates || {})[`${to}_${from}`];
  if (inv && inv.rate) return 1 / Number(inv.rate);
  return null;
}

// Today as YYYY-MM-DD using local time
export function isoToday() {
  const d = new Date();
  const m = `${d.getMonth() + 1}`.padStart(2, "0");
  const day = `${d.getDate()}`.padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}
