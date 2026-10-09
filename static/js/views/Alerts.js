import { get, post, put, del, fmtDate, fmtDaysSince } from "../utils.js";

const NOW_OPEN_KEY = "horizon.alerts.nowOpen";

function readOpen() {
  try { return localStorage.getItem(NOW_OPEN_KEY) === "1"; } catch (e) { return false; }
}

// Signal threshold fields, grouped to mirror the TradingView "Horizon Signal" inputs.
const SIGNAL_GROUPS = [
  { title: "RSI", fields: [
    ["rsi_length", "RSI length"],
    ["buy_rsi_trade", "Buy: RSI max (Trade)"],
    ["buy_rsi_invest", "Buy: RSI max (Invest)"],
    ["rsi_rising_bars", "Buy: RSI rising bars"],
    ["sell_rsi_trade", "Sell: RSI min (Trade)"],
    ["sell_rsi_invest", "Sell: RSI min (Invest)"],
  ] },
  { title: "Stochastic", fields: [
    ["stoch_k_length", "Stoch %K length"],
    ["stoch_smooth_k", "Stoch %K smoothing"],
    ["stoch_d_length", "Stoch %D length"],
    ["stoch_buy_max", "Buy: Stoch %D max"],
    ["stoch_sell_min", "Sell: Stoch %D min"],
  ] },
  { title: "Volume", fields: [
    ["vol_ma_length", "Volume MA length"],
  ] },
];

export const Alerts = {
  data() {
    return {
      buy: [],
      held: [],
      stale: [],
      maxMonths: 6,
      savedMaxMonths: 6,
      savingMax: false,
      signal: null,
      signalDefaults: null,
      log: [],
      status: { status: "idle", last_summary: null, output: [], finished_at: null },
      savingSignal: false,
      checking: false,
      showSignal: false,
      now: null,          // rows of the stored snapshot (null = never taken)
      nowAt: null,        // when that snapshot was taken (UTC ISO)
      nowOpen: readOpen(),
      nowSort: "recent",  // recent | ticker
      loadingNow: false,
      pollTimer: null,
      detail: null,      // { kind: 'now' | 'log', row } — drives the detail modal
      msg: null,
      err: null,
    };
  },
  computed: {
    signalGroups() { return SIGNAL_GROUPS; },
    // Most recent last signal first; tickers with none (or a failed fetch)
    // sink to the bottom. Ties and the "ticker" sort are alphabetical.
    nowSorted() {
      const rows = [...(this.now || [])];
      const byTicker = (a, b) => a.ticker.localeCompare(b.ticker);
      if (this.nowSort === "ticker") return rows.sort(byTicker);
      const day = r => (r.last_signal && r.last_signal.date) || "";
      return rows.sort((a, b) => day(b).localeCompare(day(a)) || byTicker(a, b));
    },
    // One line for the collapsed header, so it's worth opening.
    nowSummary() {
      if (!this.now) return "not checked yet";
      const n = this.now.length;
      const parts = [`${n} ticker${n === 1 ? "" : "s"}`];
      const top = this.nowSorted[0];
      if (top && top.last_signal) {
        parts.push(`latest ${top.ticker} ${top.last_signal.action} ${fmtDaysSince(top.last_signal.date)}`);
      }
      if (this.nowAt) {
        const d = new Date(this.nowAt);
        if (!isNaN(d)) parts.push(`as of ${d.toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" })}`);
      }
      return parts.join(" · ");
    },
  },
  async mounted() {
    this.loadSnapshot();
    await this.refresh();
    await this.loadSignal();
    await this.loadLog();
    await this.loadStatus();
  },
  beforeUnmount() {
    this.stopPolling();
  },
  methods: {
    flash(m, isErr) {
      if (isErr) { this.err = m; this.msg = null; } else { this.msg = m; this.err = null; }
      setTimeout(() => { this.msg = null; this.err = null; }, 4000);
    },
    async refresh() {
      try {
        const d = await get("/api/alerts/watches");
        this.buy = d.buy || [];
        this.held = d.held || [];
        this.stale = d.stale || [];
        this.maxMonths = this.savedMaxMonths = d.max_months;
      } catch (e) { this.flash(e.message, true); }
    },
    async loadSignal() {
      try {
        const s = await get("/api/alerts/settings");
        this.signal = s.signal;
        this.signalDefaults = s.signal_defaults;
      } catch (e) { this.flash(e.message, true); }
    },
    async loadLog() {
      try { this.log = await get("/api/alerts/log?limit=40") || []; } catch (e) { console.error(e); }
    },
    async deleteLogEntry(r) {
      try {
        await del(`/api/alerts/log/${r.id}`);
        this.log = this.log.filter(x => x.id !== r.id);
        if (this.detail && this.detail.kind === "log" && this.detail.row.id === r.id) this.closeDetail();
      }
      catch (e) { this.flash(e.message, true); }
    },
    async clearLog() {
      if (!confirm("Clear all recent alerts? This only clears the history — it won't cause any signals to re-fire.")) return;
      try { await del("/api/alerts/log"); this.log = []; this.flash("Alert history cleared."); }
      catch (e) { this.flash(e.message, true); }
    },
    async loadStatus() {
      try { this.status = await get("/api/alerts/status"); } catch (e) { console.error(e); }
    },

    async saveMaxMonths() {
      const n = Math.max(0, Math.min(120, parseInt(this.maxMonths, 10) || 0));
      this.savingMax = true;
      try {
        await put("/api/alerts/settings", { alert_research_max_months: n });
        await this.refresh();
        this.flash(n ? `Buy list now skips research older than ${n} month${n === 1 ? "" : "s"}.` : "Buy list now includes research of any age.");
      } catch (e) { this.flash(e.message, true); }
      finally { this.savingMax = false; }
    },

    // The daily check stores its Signal-now result; reading it is local and instant.
    async loadSnapshot() {
      try { this.applySnapshot(await get("/api/alerts/snapshot")); } catch (e) { console.error(e); }
    },
    applySnapshot(s) {
      this.now = s ? (s.rows || []) : null;
      this.nowAt = s ? s.at : null;
    },
    toggleNow() {
      this.nowOpen = !this.nowOpen;
      try { localStorage.setItem(NOW_OPEN_KEY, this.nowOpen ? "1" : "0"); } catch (e) { /* private mode */ }
    },
    // Re-run it against the latest closed bar — no push, no dedupe — and keep the result.
    async loadNow() {
      this.loadingNow = true;
      try { this.applySnapshot(await get("/api/alerts/now")); }
      catch (e) { this.flash(e.message, true); }
      finally { this.loadingNow = false; }
    },
    deliveryLabel(d) {
      if (d === "sent") return "alerted";
      if (d === "missed") return "never sent";
      // Past the catch-up window — the next check won't push it either.
      if (d === "stale") return "too old to push";
      return "next check";
    },
    deliveryClass(d) {
      if (d === "sent") return "text-muted";
      if (d === "missed") return "text-red";
      if (d === "stale") return "text-muted";
      return "text-green";
    },

    async saveSignal() {
      this.savingSignal = true;
      try { await put("/api/alerts/settings", { signal: this.signal }); await this.loadSignal(); this.flash("Signal settings saved."); }
      catch (e) { this.flash(e.message, true); }
      finally { this.savingSignal = false; }
    },
    resetSignal() {
      if (this.signalDefaults) this.signal = { ...this.signalDefaults };
    },

    async checkNow() {
      this.checking = true;
      try {
        await post("/api/alerts/check-now", {});
        this.startPolling();
      } catch (e) { this.flash(e.message, true); this.checking = false; }
    },
    startPolling() {
      this.stopPolling();
      this.pollTimer = setInterval(async () => {
        await this.loadStatus();
        if (this.status.status !== "running") {
          this.stopPolling();
          this.checking = false;
          await Promise.all([this.loadLog(), this.loadSnapshot()]);
          const s = this.status.last_summary;
          if (s) this.flash(`Checked ${s.checked} · sent ${s.fired}` + (s.failed ? ` · ${s.failed} failed` : ""));
        }
      }, 1500);
    },
    stopPolling() {
      if (this.pollTimer) { clearInterval(this.pollTimer); this.pollTimer = null; }
    },
    // ── Minimal rows: the list shows ticker + age + action; everything else lives in the modal.
    openDetail(kind, row) { this.detail = { kind, row }; },
    closeDetail() { this.detail = null; },

    // Signal-now row: the badge is the *last* signal's action (the one to read),
    // with "now" flagged separately when today's bar is also an edge.
    nowAction(r) { return r.last_signal ? r.last_signal.action : null; },
    nowSubtitle(r) {
      if (r.error) return "couldn’t load prices";
      if (!r.last_signal) return "no signal in 2y";
      return `${fmtDaysSince(r.last_signal.date)} · ${this.deliveryLabel(r.last_signal.delivery)}`;
    },
    nowSubtitleClass(r) {
      if (r.error) return "text-red";
      if (!r.last_signal) return "text-muted";
      return this.deliveryClass(r.last_signal.delivery);
    },
    logSubtitle(r) { return `${fmtDaysSince(r.sent_at)} · ${r.ok ? "sent" : "failed"}`; },

    fx(v, digits = 1) { return v == null ? "—" : Number(v).toFixed(digits); },
    kindBadge(kind) { return kind === "Invest" ? "blue" : "green"; },
    actionBadge(a) { return a === "SELL" ? "red" : (a === "ADD" ? "orange" : "green"); },
  },
  setup() { return { fmtDate, fmtDaysSince }; },
  template: `
  <div class="alerts-view">
    <div class="view-head">
      <h1>Alerts</h1>
      <button class="btn-ghost" :disabled="checking" @click="checkNow">
        {{ checking ? 'Checking…' : '↻ Check now' }}
      </button>
    </div>

    <p v-if="msg" class="text-green">{{ msg }}</p>
    <p v-if="err" class="text-red">{{ err }}</p>

    <div class="alerts-grid">
      <!-- BUY list — derived from Research -->
      <div class="card">
        <div class="card-head">
          <h3>Buy</h3>
          <span class="text-muted">TRADE / INVEST research · watching for BUY</span>
        </div>
        <table v-if="buy.length" class="table">
          <thead><tr><th>Ticker</th><th>Kind</th><th class="num">Researched</th></tr></thead>
          <tbody>
            <tr v-for="w in buy" :key="w.id">
              <td><strong>{{ w.ticker }}</strong></td>
              <td><span class="badge" :class="kindBadge(w.kind)">{{ w.kind }}</span></td>
              <td class="num text-muted">{{ fmtDaysSince(w.date_researched) }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="empty">Nothing to watch. Research a ticker with a TRADE or INVEST decision and it appears here.</p>

        <div class="max-age-row">
          <label>Skip research older than</label>
          <input type="number" min="0" max="120" v-model.number="maxMonths" @keyup.enter="saveMaxMonths">
          <span class="text-muted">months</span>
          <button v-if="maxMonths !== savedMaxMonths" class="btn-ghost sm" :disabled="savingMax" @click="saveMaxMonths">
            {{ savingMax ? 'Saving…' : 'Save' }}
          </button>
          <span class="text-muted sig-note">0 = no limit</span>
        </div>
        <div v-if="stale.length" class="seed-box">
          <span class="text-muted">Skipped — too old, re-research to include:</span>
          <span v-for="s in stale" :key="s.ticker" class="pill" :title="'Researched ' + s.date_researched">
            {{ s.ticker }} <span class="text-muted">{{ fmtDaysSince(s.date_researched) }}</span>
          </span>
        </div>
      </div>

      <!-- HELD list — derived from open trades -->
      <div class="card">
        <div class="card-head">
          <h3>Held</h3>
          <span class="text-muted">open trades · watching to ADD or SELL</span>
        </div>
        <table v-if="held.length" class="table">
          <thead><tr><th>Ticker</th><th>Kind</th></tr></thead>
          <tbody>
            <tr v-for="w in held" :key="w.id">
              <td><strong>{{ w.ticker }}</strong></td>
              <td><span class="badge" :class="kindBadge(w.kind)">{{ w.kind }}</span></td>
            </tr>
          </tbody>
        </table>
        <p v-else class="empty">No open trades. Log a trade and it appears here; close it and it drops off.</p>
      </div>
    </div>

    <p class="text-muted sig-note">Both lists update themselves from Research and Trades — there's nothing to add or remove here.</p>

    <!-- Signal settings (mirror TradingView) -->
    <div class="card" v-if="signal">
      <div class="card-head collapsible" @click="showSignal = !showSignal">
        <h3>Signal settings <span class="chev">{{ showSignal ? '▾' : '▸' }}</span></h3>
        <span class="text-muted">match your TradingView “Horizon Signal” inputs</span>
      </div>
      <template v-if="showSignal">
        <div class="signal-groups">
          <div v-for="g in signalGroups" :key="g.title" class="signal-group">
            <h4>{{ g.title }}</h4>
            <div class="sig-field" v-for="f in g.fields" :key="f[0]">
              <label>{{ f[1] }}</label>
              <input type="number" v-model.number="signal[f[0]]">
            </div>
            <label v-if="g.title === 'Volume'" class="check-inline">
              <input type="checkbox" v-model="signal.use_vol_filter"> Buy: require volume &gt; MA
            </label>
          </div>
        </div>
        <div class="toolbar">
          <button class="btn-primary" :disabled="savingSignal" @click="saveSignal">
            {{ savingSignal ? 'Saving…' : 'Save signal settings' }}
          </button>
          <button class="btn-ghost" @click="resetSignal">Reset to TradingView defaults</button>
        </div>
        <p class="text-muted sig-note">RSI rising bars: 0 = off, 1 = today &gt; yesterday, 2+ = N consecutive up-bars.
          These apply to every watched ticker on the next check.</p>
      </template>
    </div>

    <!-- Signal right now (read-only; ignores dedupe) -->
    <div class="card">
      <div class="card-head collapsible" tabindex="0" @click="toggleNow" @keyup.enter="toggleNow">
        <h3>Signal now <span class="chev">{{ nowOpen ? '▾' : '▸' }}</span></h3>
        <span class="text-muted">{{ nowSummary }}</span>
        <div class="spacer"></div>
        <button class="btn-ghost sm" :disabled="loadingNow" @click.stop="loadNow" @keyup.enter.stop>
          {{ loadingNow ? 'Loading…' : (now ? '↻ Refresh' : 'Check signals') }}
        </button>
      </div>

      <template v-if="nowOpen">
      <div v-if="now && now.length > 1" class="toolbar">
        <span class="text-muted">Sort</span>
        <div class="seg">
          <button :class="{ on: nowSort === 'recent' }" @click="nowSort = 'recent'">Last signal</button>
          <button :class="{ on: nowSort === 'ticker' }" @click="nowSort = 'ticker'">Ticker</button>
        </div>
      </div>

      <ul v-if="now && now.length" class="mini-list">
        <li v-for="r in nowSorted" :key="r.ticker" class="mini-row" tabindex="0"
            @click="openDetail('now', r)" @keyup.enter="openDetail('now', r)">
          <div class="mini-main">
            <span class="mini-ticker">{{ r.ticker }}</span>
            <span v-if="r.action" class="tag-now">now</span>
            <span class="mini-sub" :class="nowSubtitleClass(r)">{{ nowSubtitle(r) }}</span>
          </div>
          <span v-if="nowAction(r)" class="badge" :class="actionBadge(nowAction(r))">{{ nowAction(r) }}</span>
          <span v-else class="text-muted">—</span>
          <span class="mini-chev">›</span>
        </li>
      </ul>
      <p v-else-if="now" class="empty">No active watches.</p>
      <p v-else class="empty">Filled in by the daily check. Press “Check signals” to evaluate every watched ticker now.</p>

      <p v-if="now && now.length" class="text-muted sig-note">Updated by the daily check · tap a ticker for prices, RSI and stochastics.</p>
      </template>
    </div>

    <!-- Recent alerts -->
    <div class="card">
      <div class="card-head">
        <h3>Recent alerts</h3>
        <div class="spacer"></div>
        <button v-if="log.length" class="btn-ghost sm" @click="clearLog">Clear all</button>
      </div>
      <ul v-if="log.length" class="mini-list">
        <li v-for="r in log" :key="r.id" class="mini-row" tabindex="0"
            @click="openDetail('log', r)" @keyup.enter="openDetail('log', r)">
          <div class="mini-main">
            <span class="mini-ticker">{{ r.ticker }}</span>
            <span class="mini-list-tag">{{ r.bucket || '—' }}</span>
            <span class="mini-sub" :class="r.ok ? 'text-muted' : 'text-red'">{{ logSubtitle(r) }}</span>
          </div>
          <span v-if="r.action" class="badge" :class="actionBadge(r.action)">{{ r.action }}</span>
          <span v-else class="text-muted">—</span>
          <span class="mini-chev">›</span>
        </li>
      </ul>
      <p v-else class="empty">No alerts yet.</p>
    </div>

    <!-- Detail modal — everything the minimal rows leave out -->
    <div v-if="detail" class="modal-backdrop" @click.self="closeDetail">
      <div class="modal detail-modal">
        <div class="detail-head">
          <h3>{{ detail.row.ticker }}</h3>
          <span v-if="detail.kind === 'now' && detail.row.action" class="badge" :class="actionBadge(detail.row.action)">
            {{ detail.row.action }} now
          </span>
          <span v-else-if="detail.kind === 'log' && detail.row.action" class="badge" :class="actionBadge(detail.row.action)">
            {{ detail.row.action }}
          </span>
          <div class="spacer"></div>
          <button class="icon-btn" @click="closeDetail" title="Close">✕</button>
        </div>

        <!-- Signal now -->
        <template v-if="detail.kind === 'now'">
          <dl class="detail-list">
            <div><dt>List</dt><dd>{{ detail.row.bucket }}</dd></div>
            <div><dt>Bar</dt><dd>{{ detail.row.bar_date || '—' }}</dd></div>
            <div><dt>Price</dt><dd class="num">{{ fx(detail.row.close, 2) }}</dd></div>
            <div><dt>RSI</dt><dd class="num">{{ fx(detail.row.rsi) }}</dd></div>
            <div><dt>Stoch %K</dt><dd class="num">{{ fx(detail.row.k) }}</dd></div>
            <div><dt>Stoch %D</dt><dd class="num">{{ fx(detail.row.d) }}</dd></div>
            <div><dt>Signal now</dt>
              <dd>
                <span v-if="detail.row.action" class="badge" :class="actionBadge(detail.row.action)">{{ detail.row.action }}</span>
                <span v-else class="text-muted">none</span>
              </dd>
            </div>
            <div><dt>Last signal</dt>
              <dd>
                <template v-if="detail.row.last_signal">
                  <span class="badge" :class="actionBadge(detail.row.last_signal.action)">{{ detail.row.last_signal.action }}</span>
                  <span class="text-muted"> {{ detail.row.last_signal.date }} · {{ fmtDaysSince(detail.row.last_signal.date) }} · </span>
                  <span :class="deliveryClass(detail.row.last_signal.delivery)">{{ deliveryLabel(detail.row.last_signal.delivery) }}</span>
                </template>
                <span v-else class="text-muted">none in 2y</span>
              </dd>
            </div>
          </dl>
          <p v-if="detail.row.error" class="text-red sig-note">{{ detail.row.error }}</p>
          <p class="text-muted sig-note">
            “Now” is an edge on the latest closed bar, so it clears the day after it fires — “Last signal” is the one to read.
            <span class="text-red">never sent</span> means the ticker was armed past that bar.
          </p>
        </template>

        <!-- Recent alert -->
        <template v-else>
          <dl class="detail-list">
            <div><dt>Sent</dt><dd>{{ fmtDate(detail.row.sent_at) }} <span class="text-muted">· {{ fmtDaysSince(detail.row.sent_at) }}</span></dd></div>
            <div><dt>List</dt><dd>{{ detail.row.bucket || '—' }}</dd></div>
            <div><dt>Bar</dt><dd>{{ detail.row.bar_date || '—' }}</dd></div>
            <div><dt>Price</dt><dd class="num">{{ detail.row.price != null ? detail.row.price.toFixed(2) : '—' }}</dd></div>
            <div><dt>Status</dt>
              <dd>
                <span v-if="detail.row.ok" class="text-muted">sent</span>
                <span v-else class="text-red">failed</span>
              </dd>
            </div>
          </dl>
          <p v-if="detail.row.error" class="text-red sig-note">{{ detail.row.error }}</p>
          <div class="modal-actions">
            <button class="btn-ghost" @click="deleteLogEntry(detail.row)">Remove from history</button>
          </div>
        </template>
      </div>
    </div>
  </div>
  `,
};
