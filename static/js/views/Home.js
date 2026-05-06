import { get, fmtPct, fmtMoney } from "../utils.js";

export const Home = {
  props: ["gate"],
  data() {
    return {
      researchCount: null,
      openTrades: null,
      monthRoi: null,
      loaded: false,
    };
  },
  computed: {
    bannerClass() {
      if (!this.gate) return "";
      return (this.gate.crash_risk || "").toLowerCase();
    },
    headline() {
      if (!this.gate) return "NO MARKET CHECK YET";
      if (this.gate.crash_risk === "OK") return "CAN TRADE";
      if (this.gate.crash_risk === "CAUTION") return "CAUTION";
      if (this.gate.crash_risk === "NO_TRADE") return "NO TRADE";
      return "—";
    },
    subtitle() {
      if (!this.gate) return "Run today's market check to set the gate.";
      const lvl = this.gate.position_size_level;
      const pct = this.gate.position_size_pct;
      if (this.gate.crash_risk === "OK" && lvl) {
        return `Position size: ${lvl} — ${pct}% per stock (max 5%)`;
      }
      if (this.gate.crash_risk === "CAUTION") return "Crash signals are mixed — proceed with care.";
      if (this.gate.crash_risk === "NO_TRADE") return "Crash conditions detected — sit on your hands today.";
      return "";
    },
  },
  async mounted() {
    try {
      const [research, trades, perf] = await Promise.all([
        get("/api/research"),
        get("/api/trades"),
        get(`/api/trades/performance?year=${new Date().getFullYear()}`),
      ]);
      this.researchCount = research.length;
      this.openTrades = trades.filter(t => !t.exit_date).length;
      const m = `${new Date().getMonth() + 1}`.padStart(2, "0");
      const cur = perf.months.find(x => x.month === m);
      this.monthRoi = cur ? cur.total_roi : 0;
      this.loaded = true;
    } catch (e) {
      console.error(e);
    }
  },
  template: `
    <div>
      <div class="banner" :class="bannerClass">
        <h1>{{ headline }}</h1>
        <div class="subtitle">{{ subtitle }}</div>
      </div>

      <div class="grid-3">
        <div class="stat">
          <div class="label">Researched</div>
          <div class="value">{{ researchCount ?? '—' }}</div>
        </div>
        <div class="stat">
          <div class="label">Open Trades</div>
          <div class="value">{{ openTrades ?? '—' }}</div>
        </div>
        <div class="stat">
          <div class="label">This Month ROI</div>
          <div class="value" :class="{ 'text-green': monthRoi > 0, 'text-red': monthRoi < 0 }">
            {{ monthRoi != null ? monthRoi.toFixed(2) + '%' : '—' }}
          </div>
        </div>
      </div>

      <div class="card" v-if="gate && gate.notes">
        <h3>Today's notes</h3>
        <p style="white-space: pre-wrap; margin: 0;">{{ gate.notes }}</p>
      </div>

      <div class="card" v-if="gate">
        <h3>Today's indicators</h3>
        <div class="grid-3">
          <div><span class="text-muted">St. Louis Fed:</span> {{ gate.st_louis_fed }}</div>
          <div><span class="text-muted">VIX:</span> {{ gate.vix }}</div>
          <div><span class="text-muted">RSI:</span> {{ gate.rsi }}</div>
          <div><span class="text-muted">STO:</span> {{ gate.stochastic }}</div>
          <div><span class="text-muted">S5FI:</span> {{ gate.s5fi }}</div>
          <div><span class="text-muted">Fear/Greed:</span> {{ gate.fear_greed }}</div>
        </div>
      </div>
    </div>
  `,
};
