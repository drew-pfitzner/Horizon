import { Home } from "./views/Home.js";
import { MarketCheck } from "./views/MarketCheck.js";
import { Research } from "./views/Research.js";
import { Valuation } from "./views/Valuation.js";
import { Trades } from "./views/Trades.js";
import { SmartMoney } from "./views/SmartMoney.js";
import { Settings } from "./views/Settings.js";
import { get } from "./utils.js";

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
    { path: "/trades", component: Trades },
    { path: "/smart-money", component: SmartMoney },
    { path: "/settings", component: Settings },
  ],
});

const app = createApp({
  data() {
    return { gate: null };
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
  },
  methods: {
    async loadGate() {
      try {
        const data = await get("/api/market-check/today");
        this.gate = data;
      } catch (e) {
        console.error("loadGate", e);
        this.gate = null;
      }
    },
  },
  async mounted() {
    await this.loadGate();
  },
});

app.use(router);
app.mount("#app");
