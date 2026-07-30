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
    return { gate: null, mobileMenuOpen: false, portfolio: { value: 0, currency: "AUD" }, fxRates: {} };
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
    // Hover tooltip: per-stock position size in dollar terms (base + USD).
    gateTitle() {
      if (!this.gate || this.gate.crash_risk !== "OK") return "";
      const pct = Number(this.gate.position_size_pct);
      if (!pct || !this.portfolio.value) return "";
      const baseCcy = (this.portfolio.currency || "AUD").toUpperCase();
      const base = this.portfolio.value * pct / 100;
      let s = `Position size ${pct}% = ${fmtCcy(base, baseCcy)} ${baseCcy}`;
      const rate = fxRate(this.fxRates, baseCcy, "USD");
      if (baseCcy !== "USD" && rate != null) s += ` ≈ ${fmtCcy(base * rate, "USD")} USD`;
      return s;
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
        const [portfolio, fx] = await Promise.all([
          get("/api/settings/portfolio"),
          get("/api/settings/fx-rates"),
        ]);
        this.portfolio = { value: Number(portfolio.value) || 0, currency: portfolio.currency || "AUD" };
        this.fxRates = fx || {};
      } catch (e) { console.error("loadPortfolioFx", e); }
    },
  },
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
