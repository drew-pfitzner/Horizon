import { get, fmtPct, fmtMoney } from "../utils.js";

const QUOTE_CCY = "USD"; // secondary display currency on the home page

export const Home = {
  props: ["gate"],
  data() {
    return {
      researchCount: null,
      openTrades: null,
      monthRoi: null,
      loaded: false,
      portfolio: { value: 0, currency: "AUD" },
      maxPositionPct: 5,
      fxRates: {},
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
        return `Position size: ${lvl} — ${pct}% per stock (max ${this.maxPositionPct}%)`;
      }
      if (this.gate.crash_risk === "CAUTION") return "Crash signals are mixed — proceed with care.";
      if (this.gate.crash_risk === "NO_TRADE") return "Crash conditions detected — sit on your hands today.";
      return "";
    },
    todayPct() {
      if (this.gate && this.gate.crash_risk === "OK" && this.gate.position_size_pct) {
        return Number(this.gate.position_size_pct);
      }
      return null;
    },
    baseCcy() { return (this.portfolio.currency || "AUD").toUpperCase(); },
    quoteCcy() { return QUOTE_CCY; },
    showQuote() { return this.baseCcy !== this.quoteCcy; },
    baseToQuoteRate() { return this.fxRate(this.baseCcy, this.quoteCcy); },
    quoteToBaseRate() { return this.fxRate(this.quoteCcy, this.baseCcy); },
    todayInBase() {
      if (this.todayPct == null || !this.portfolio.value) return null;
      return this.portfolio.value * this.todayPct / 100;
    },
    todayInQuote() {
      if (this.todayInBase == null || this.baseToQuoteRate == null) return null;
      return this.todayInBase * this.baseToQuoteRate;
    },
    maxInBase() {
      if (!this.portfolio.value) return null;
      return this.portfolio.value * this.maxPositionPct / 100;
    },
    maxInQuote() {
      if (this.maxInBase == null || this.baseToQuoteRate == null) return null;
      return this.maxInBase * this.baseToQuoteRate;
    },
  },
  async mounted() {
    try {
      const [research, trades, perf, portfolio, maxPct, fx] = await Promise.all([
        get("/api/research"),
        get("/api/trades"),
        get(`/api/trades/performance?year=${new Date().getFullYear()}`),
        get("/api/settings/portfolio"),
        get("/api/settings/max-position-pct"),
        get("/api/settings/fx-rates"),
      ]);
      this.researchCount = research.length;
      this.openTrades = trades.filter(t => !t.exit_date).length;
      const m = `${new Date().getMonth() + 1}`.padStart(2, "0");
      const cur = perf.months.find(x => x.month === m);
      this.monthRoi = cur ? cur.total_roi : 0;
      this.portfolio = { value: Number(portfolio.value) || 0, currency: portfolio.currency || "AUD" };
      this.maxPositionPct = Number(maxPct) || 5;
      this.fxRates = fx || {};
      this.loaded = true;
    } catch (e) {
      console.error(e);
    }
  },
  methods: {
    fxRate(from, to) {
      from = (from || "USD").toUpperCase();
      to = (to || "USD").toUpperCase();
      if (from === to) return 1;
      const e = this.fxRates[`${from}_${to}`];
      if (e && e.rate) return Number(e.rate);
      const inv = this.fxRates[`${to}_${from}`];
      if (inv && inv.rate) return 1 / Number(inv.rate);
      return null;
    },
    fmtCcy(n, ccy) {
      if (n == null || isNaN(n)) return "—";
      try {
        return Number(n).toLocaleString("en-US", {
          style: "currency", currency: ccy || "USD",
          minimumFractionDigits: 0, maximumFractionDigits: 0,
        });
      } catch (e) {
        return `${ccy} ${Math.round(Number(n)).toLocaleString()}`;
      }
    },
  },
  template: `
    <div>
      <div class="banner" :class="bannerClass">
        <h1>{{ headline }}</h1>
        <div class="subtitle">{{ subtitle }}</div>

        <div v-if="todayPct != null && portfolio.value" class="banner-position">
          <div class="banner-position-amounts">
            <div class="banner-amount primary">
              {{ fmtCcy(todayInBase, baseCcy) }}
              <span class="banner-amount-ccy">{{ baseCcy }}</span>
            </div>
            <div v-if="showQuote" class="banner-amount primary">
              ≈ {{ fmtCcy(todayInQuote, quoteCcy) }}
              <span class="banner-amount-ccy">{{ quoteCcy }}</span>
            </div>
          </div>
          <div v-if="showQuote && baseToQuoteRate != null" class="banner-position-meta">
            {{ quoteCcy }}/{{ baseCcy }} @ {{ baseToQuoteRate.toFixed(4) }}
          </div>
        </div>
      </div>

      <div class="grid-3 home-stats">
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

      <div class="grid-2">
        <div class="card trade-rule-card">
          <h3 style="color: var(--green);">Buy Technicals</h3>
          <ul class="rule-list">
            <li>RSI &lt; 35 <span class="text-muted">(preferably &lt; 30)</span></li>
            <li>RSI ticking up</li>
            <li>STO Fast &lt; 20</li>
            <li>STO Crossover: Fast over Slow</li>
          </ul>
        </div>

        <div class="card trade-rule-card">
          <h3 style="color: var(--red);">Sell Technicals</h3>
          <ul class="rule-list">
            <li>RSI &gt; 70 then cross below 70</li>
            <li>STO Fast &gt; 80</li>
            <li>STO Crossover: Slow over Fast</li>
          </ul>
          <div style="margin-top: 1rem; padding-top: 1rem; border-top: 1px solid var(--border);">
            <div style="font-size: 0.85rem; color: var(--text-2); margin-bottom: 0.4rem; font-weight: 600;">Risk Management</div>
            <ul class="rule-list" style="margin-bottom: 0;">
              <li>Stop Loss &gt; 7% from Buy Price</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  `,
};
