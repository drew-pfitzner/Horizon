import { get, fmtDaysSince, fmtDateTime } from "../utils.js";

const QUOTE_CCY = "USD"; // secondary display currency on the home page

// The technicals cards are reference material, not a daily read — the alerts job
// checks these conditions itself now. Collapsed by default, with the thresholds
// that matter summarised on the header line; the choice is remembered.
const RULES_KEY = "horizon.home.rulesOpen";

const RECENT_ALERTS = 5; // enough to see the week without turning Home into a log

export const Home = {
  props: ["gate"],
  data() {
    return {
      researchCount: null,
      openTrades: null,
      perf: null,
      alerts: null,
      smSchedule: null,
      loaded: false,
      portfolio: { value: 0, currency: "AUD" },
      maxPositionPct: 5,
      fxRates: {},
      rulesOpen: localStorage.getItem(RULES_KEY) === "1",
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
    todayInBase() {
      if (this.todayPct == null || !this.portfolio.value) return null;
      return this.portfolio.value * this.todayPct / 100;
    },
    todayInQuote() {
      if (this.todayInBase == null || this.baseToQuoteRate == null) return null;
      return this.todayInBase * this.baseToQuoteRate;
    },

    // ── Performance headline numbers ────────────────────────────────────────
    // Two different questions, which is why both are here: avg ROI weights every
    // closed trade equally (is the *method* working?), ROC weights by money
    // (what did the account actually earn this year?).
    overall() { return this.perf ? this.perf.overall : null; },
    avgRoi() { return this.overall ? this.overall.avg_roi : null; },
    closedCount() { return this.overall ? this.overall.closed : null; },
    roc() { return this.overall ? this.overall.return_on_capital : null; },
    perfYear() { return this.perf ? this.perf.year : new Date().getFullYear(); },

    // ── Recent alerts ───────────────────────────────────────────────────────
    // Failure rows (a price fetch that didn't land) carry no action and aren't
    // something to act on, so they stay on the Alerts tab.
    recentAlerts() {
      if (!this.alerts) return null;
      return this.alerts
        .filter(r => r.ok && r.action)
        .sort((a, b) => String(b.sent_at || "").localeCompare(String(a.sent_at || "")))
        .slice(0, RECENT_ALERTS);
    },

    smLastRun() {
      if (!this.smSchedule) return null;
      return this.smSchedule.last_run || this.smSchedule.last_auto_run || null;
    },
  },
  async mounted() {
    // One round trip each, all cheap — nothing here fetches prices.
    const settle = (p) => p.catch(e => { console.error(e); return null; });
    const [research, trades, perf, alerts, sm, portfolio, maxPct, fx] = await Promise.all([
      settle(get("/api/research")),
      settle(get("/api/trades")),
      settle(get(`/api/trades/performance?year=${new Date().getFullYear()}`)),
      settle(get(`/api/alerts/log?limit=${RECENT_ALERTS * 4}`)),
      settle(get("/api/smart-money/schedule")),
      settle(get("/api/settings/portfolio")),
      settle(get("/api/settings/max-position-pct")),
      settle(get("/api/settings/fx-rates")),
    ]);
    if (research) this.researchCount = research.length;
    if (trades) this.openTrades = trades.filter(t => !t.exit_date).length;
    this.perf = perf;
    this.alerts = alerts || [];
    this.smSchedule = sm;
    if (portfolio) {
      this.portfolio = { value: Number(portfolio.value) || 0, currency: portfolio.currency || "AUD" };
    }
    this.maxPositionPct = Number(maxPct) || 5;
    this.fxRates = fx || {};
    this.loaded = true;
  },
  methods: {
    go(path) { this.$router.push(path); },
    toggleRules() {
      this.rulesOpen = !this.rulesOpen;
      localStorage.setItem(RULES_KEY, this.rulesOpen ? "1" : "0");
    },
    signClass(n) {
      if (n == null) return "";
      return n > 0 ? "text-green" : (n < 0 ? "text-red" : "");
    },
    pct(n, digits = 2) {
      return n == null ? "—" : `${Number(n).toFixed(digits)}%`;
    },
    // BUY = a researched name hit its entry; ADD = an open position did;
    // SELL = an open position hit its exit. Colours match the Alerts tab.
    actionBadge(a) { return a === "SELL" ? "red" : (a === "ADD" ? "orange" : "green"); },
    alertSubtitle(r) {
      const when = fmtDaysSince(r.sent_at);
      const where = r.bucket === "HELD" ? "held" : "watchlist";
      return `${when} · ${where}${r.kind ? ` · ${r.kind}` : ""}`;
    },
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
  setup() { return { fmtDaysSince, fmtDateTime }; },
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

      <!-- Every tile is a way through to the tab that owns the number. -->
      <div class="grid-4 home-stats">
        <div class="stat stat-link" role="button" tabindex="0"
             @click="go('/research')" @keyup.enter="go('/research')">
          <div class="label">Researched</div>
          <div class="value">{{ researchCount ?? '—' }}</div>
          <div class="stat-note">stocks on file</div>
        </div>

        <div class="stat stat-link" role="button" tabindex="0"
             @click="go('/trades')" @keyup.enter="go('/trades')">
          <div class="label">Open Trades</div>
          <div class="value">{{ openTrades ?? '—' }}</div>
          <div class="stat-note">positions live</div>
        </div>

        <div class="stat stat-link" role="button" tabindex="0"
             @click="go('/trades')" @keyup.enter="go('/trades')"
             title="Mean ROI across every closed trade — each trade counts once, regardless of size.">
          <div class="label">Avg ROI</div>
          <div class="value" :class="signClass(avgRoi)">{{ pct(avgRoi) }}</div>
          <div class="stat-note">
            {{ closedCount != null ? closedCount + ' closed · all-time' : 'all-time' }}
          </div>
        </div>

        <div class="stat stat-link" role="button" tabindex="0"
             @click="go('/trades')" @keyup.enter="go('/trades')"
             title="Realised P/L this year as a share of portfolio value.">
          <div class="label">Return on Capital</div>
          <div class="value" v-if="roc != null" :class="signClass(roc)">{{ pct(roc) }}</div>
          <div class="value text-muted" v-else style="font-size: 1rem;">Set portfolio</div>
          <div class="stat-note">{{ perfYear }}</div>
        </div>
      </div>

      <div class="grid-2">
        <!-- Recent alerts — the buy/add/sell the phone already pushed. -->
        <div class="card">
          <div class="card-head">
            <h3>Recent alerts</h3>
            <div class="spacer"></div>
            <button class="btn-ghost sm" @click="go('/alerts')">All alerts ›</button>
          </div>

          <ul v-if="recentAlerts && recentAlerts.length" class="mini-list">
            <li v-for="r in recentAlerts" :key="r.id" class="mini-row" tabindex="0"
                @click="go('/alerts')" @keyup.enter="go('/alerts')">
              <div class="mini-main">
                <span class="mini-ticker">{{ r.ticker }}</span>
                <span class="mini-sub text-muted">{{ alertSubtitle(r) }}</span>
              </div>
              <span class="badge" :class="actionBadge(r.action)">{{ r.action }}</span>
              <span class="mini-chev">›</span>
            </li>
          </ul>
          <p v-else-if="recentAlerts" class="empty">
            No alerts yet. Research a stock or open a trade and the check watches it from then on.
          </p>
          <p v-else class="empty">Loading…</p>
        </div>

        <!-- Data freshness: the one thing that silently goes stale. -->
        <div class="card">
          <div class="card-head">
            <h3>Smart money</h3>
            <div class="spacer"></div>
            <button class="btn-ghost sm" @click="go('/smart-money')">Open ›</button>
          </div>

          <ul class="mini-list">
            <li class="mini-row" tabindex="0" @click="go('/smart-money')" @keyup.enter="go('/smart-money')">
              <div class="mini-main">
                <span class="mini-ticker">Last updated</span>
                <span class="mini-sub text-muted" v-if="smLastRun">{{ fmtDateTime(smLastRun) }}</span>
                <span class="mini-sub text-muted" v-else>no run recorded — update from the Smart Money tab</span>
              </div>
              <span class="text-muted">{{ smLastRun ? fmtDaysSince(smLastRun) : '—' }}</span>
              <span class="mini-chev">›</span>
            </li>
            <li class="mini-row" tabindex="0" @click="go('/settings')" @keyup.enter="go('/settings')">
              <div class="mini-main">
                <span class="mini-ticker">Weekly auto-update</span>
                <span class="mini-sub text-muted" v-if="smSchedule && smSchedule.enabled">
                  next {{ fmtDateTime(smSchedule.next_run) }} · {{ smSchedule.timezone }}
                </span>
                <span class="mini-sub text-muted" v-else>off — 13Fs land in bursts, weekly keeps it current</span>
              </div>
              <span v-if="smSchedule && smSchedule.enabled" class="badge green">ON</span>
              <span v-else class="text-muted">off</span>
              <span class="mini-chev">›</span>
            </li>
          </ul>
        </div>
      </div>

      <!-- Technicals reference. The alerts job checks these itself, so it stays
           folded away until you want to read the thresholds. -->
      <div class="card rules-card">
        <div class="card-head collapsible" @click="toggleRules">
          <h3>Technicals <span class="chev">{{ rulesOpen ? '▾' : '▸' }}</span></h3>
          <span v-if="!rulesOpen" class="rules-summary">
            <span class="text-green">Buy</span> RSI &lt; 35 · STO &lt; 20 · fast over slow
            <span class="rules-sep">|</span>
            <span class="text-red">Sell</span> RSI &gt; 70 · STO &gt; 80 · slow over fast
            <span class="rules-sep">|</span>
            <span class="text-orange">Stop</span> 7%
          </span>
        </div>

        <div v-if="rulesOpen" class="grid-2 rules-body">
          <div class="trade-rule-card">
            <h3 style="color: var(--green);">Buy Technicals</h3>
            <ul class="rule-list">
              <li>RSI &lt; 35 <span class="text-muted">(preferably &lt; 30)</span></li>
              <li>RSI ticking up</li>
              <li>STO Fast &lt; 20</li>
              <li>STO Crossover: Fast over Slow</li>
            </ul>
          </div>

          <div class="trade-rule-card">
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
    </div>
  `,
};
