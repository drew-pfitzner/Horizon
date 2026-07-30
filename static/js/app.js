import { Home } from "./views/Home.js";
import { MarketCheck } from "./views/MarketCheck.js";
import { Research } from "./views/Research.js";
import { Valuation } from "./views/Valuation.js";
import { Alerts } from "./views/Alerts.js";
import { Trades } from "./views/Trades.js";
import { SmartMoney } from "./views/SmartMoney.js";
import { Settings } from "./views/Settings.js";
import { get, isoToday, fmtCcy, fxRate } from "./utils.js";

const { createApp } = Vue;
const { createRouter, createWebHashHistory } = VueRouter;

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: "/", component: Home },
    { path: "/market-check", component: MarketCheck },
    { path: "/research", component: Research },
    { path: "/research/:id", component: Research, props: true },
    { path: "/valuation", component: Valuation },
    { path: "/valuation/:ticker", component: Valuation, props: true },
    { path: "/alerts", component: Alerts },
    { path: "/trades", component: Trades },
    { path: "/smart-money", component: SmartMoney },
    { path: "/settings", component: Settings },
  ],
});

const app = createApp({
  data() {
    return { gate: null, mobileMenuOpen: false, gatePopOpen: false,
             portfolio: { value: 0, currency: "AUD" }, maxPositionPct: 5, fxRates: {} };
  },
  computed: {
    gateClass() {
      if (!this.gate) return "unknown";
      const r = (this.gate.crash_risk || "").toLowerCase();
      return r || "unknown";
    },
    gateLabel() {
      if (!this.gate) return "NO CHECK TODAY";
      if (this.gate.crash_risk === "OK") return `CAN TRADE — ${this.gate.position_size_level || "?"}`;
      if (this.gate.crash_risk === "CAUTION") return "CAUTION";
      if (this.gate.crash_risk === "NO_TRADE") return "NO TRADE";
      return "—";
    },
    // Hover popover: headline + per-stock position size in dollar terms.
    gateHeadline() {
      if (!this.gate) return "NO CHECK";
      if (this.gate.crash_risk === "OK") return "CAN TRADE";
      if (this.gate.crash_risk === "CAUTION") return "CAUTION";
      if (this.gate.crash_risk === "NO_TRADE") return "NO TRADE";
      return "—";
    },
    gateSub() {
      if (!this.gate) return "Run today's market check.";
      const lvl = this.gate.position_size_level;
      if (this.gate.crash_risk === "OK") {
        return lvl ? `${lvl} — ${this.gate.position_size_pct}% per stock (max ${this.maxPositionPct}%)` : "Cleared to trade.";
      }
      if (this.gate.crash_risk === "CAUTION") return "Crash signals mixed — proceed with care.";
      if (this.gate.crash_risk === "NO_TRADE") return "Crash conditions — sit on your hands.";
      return "";
    },
    gateBaseCcy() { return (this.portfolio.currency || "AUD").toUpperCase(); },
    gateShowQuote() { return this.gateBaseCcy !== "USD"; },
    gateRate() { return fxRate(this.fxRates, this.gateBaseCcy, "USD"); },
    gatePct() {
      if (!this.gate || this.gate.crash_risk !== "OK") return null;
      const p = Number(this.gate.position_size_pct);
      return p || null;
    },
    gateSizeBase() {
      if (this.gatePct == null || !this.portfolio.value) return null;
      return this.portfolio.value * this.gatePct / 100;
    },
    gateSizeQuote() {
      if (this.gateSizeBase == null || this.gateRate == null) return null;
      return this.gateSizeBase * this.gateRate;
    },
    gateMaxBase() {
      if (this.gatePct == null || !this.portfolio.value || !this.maxPositionPct) return null;
      return this.portfolio.value * this.maxPositionPct / 100;
    },
    gateMaxQuote() {
      if (this.gateMaxBase == null || this.gateRate == null) return null;
      return this.gateMaxBase * this.gateRate;
    },
  },
  methods: {
    async loadGate() {
      try {
        const data = await get(`/api/market-check/today?date=${isoToday()}`);
        this.gate = data;
      } catch (e) {
        console.error("loadGate", e);
        this.gate = null;
      }
    },
    async loadPortfolioFx() {
      try {
        const [portfolio, maxPct, fx] = await Promise.all([
          get("/api/settings/portfolio"),
          get("/api/settings/max-position-pct"),
          get("/api/settings/fx-rates"),
        ]);
        this.portfolio = { value: Number(portfolio.value) || 0, currency: portfolio.currency || "AUD" };
        this.maxPositionPct = Number(maxPct) || 5;
        this.fxRates = fx || {};
      } catch (e) { console.error("loadPortfolioFx", e); }
    },
  },
  setup() { return { fmtCcy }; },
  async mounted() {
    await Promise.all([this.loadGate(), this.loadPortfolioFx()]);
  },
});

// Global sortable table header component.
// Usage: <sort-th col="ticker" :sort="sort" @sort="toggleSort">Ticker</sort-th>
//        - `sort` is a reactive object { key, dir }
//        - emits `sort` with the column name; parent toggles state
//        - add :num="true" for right-aligned numeric columns
app.component("sort-th", {
  props: {
    col: { type: String, required: true },
    sort: { type: Object, required: true },
    num: { type: Boolean, default: false },
  },
  emits: ["sort"],
  computed: {
    active() { return this.sort && this.sort.key === this.col; },
    indicator() {
      if (!this.active) return " "; // em-space placeholder keeps width stable
      return this.sort.dir === "desc" ? "↓" : "↑";
    },
  },
  template: `
    <th :class="['sortable', num ? 'num' : '', active ? 'sort-active' : '']"
        @click="$emit('sort', col)">
      <span class="sort-label"><slot></slot></span>
      <span class="sort-ind">{{ indicator }}</span>
    </th>
  `,
});

app.use(router);
app.mount("#app");
