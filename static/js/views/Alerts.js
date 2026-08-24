import { get, post, put, del, fmtDate, fmtDaysSince } from "../utils.js";

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
      seed: { buy: [], held: [] },
      signal: null,
      signalDefaults: null,
      log: [],
      status: { status: "idle", last_summary: null, output: [], finished_at: null },
      addForm: { ticker: "", bucket: "BUY", kind: "Trade" },
      savingSignal: false,
      checking: false,
      showSignal: false,
      now: null,
      loadingNow: false,
      pollTimer: null,
      detail: null,      // { kind: 'now' | 'log', row } — drives the detail modal
      msg: null,
      err: null,
    };
  },
  computed: {
    signalGroups() { return SIGNAL_GROUPS; },
  },
  async mounted() {
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
        const s = await get("/api/alerts/seed");
        this.seed = s || { buy: [], held: [] };
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

    async addWatch() {
      const t = (this.addForm.ticker || "").trim().toUpperCase();
      if (!t) return;
      try {
        await post("/api/alerts/watches", { ticker: t, bucket: this.addForm.bucket, kind: this.addForm.kind });
        this.addForm.ticker = "";
        await this.refresh();
      } catch (e) { this.flash(e.message, true); }
    },
    async addSeed(ticker, bucket, kind) {
      try {
        await post("/api/alerts/watches", { ticker, bucket, kind: kind || "Trade" });
        await this.refresh();
      } catch (e) { this.flash(e.message, true); }
    },
    async moveTo(w, bucket) {
      try { await put(`/api/alerts/watches/${w.id}`, { bucket }); await this.refresh(); }
      catch (e) { this.flash(e.message, true); }
    },
    async setKind(w, kind) {
      try { await put(`/api/alerts/watches/${w.id}`, { kind }); await this.refresh(); }
      catch (e) { this.flash(e.message, true); }
    },
    async remove(w) {
      try {
        await del(`/api/alerts/watches/${w.id}`);
        this.now = this.now ? this.now.filter(r => r.ticker !== w.ticker) : null;
        await this.refresh();
      } catch (e) { this.flash(e.message, true); }
    },

    // Read-only "what does the signal look like right now?" — no push, no dedupe.
    async loadNow() {
      this.loadingNow = true;
      try { this.now = await get("/api/alerts/now") || []; }
      catch (e) { this.flash(e.message, true); }
      finally { this.loadingNow = false; }
    },
    deliveryLabel(d) {
      if (d === "sent") return "alerted";
      if (d === "missed") return "never sent";
      return "next check";
    },
    deliveryClass(d) {
      if (d === "sent") return "text-muted";
      if (d === "missed") return "text-red";
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
          await this.loadLog();
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
      <!-- BUY list -->
      <div class="card">
        <div class="card-head">
          <h3>Buy</h3>
          <span class="text-muted">watching for BUY signals</span>
        </div>
        <table v-if="buy.length" class="table">
          <thead><tr><th>Ticker</th><th>Kind</th><th></th></tr></thead>
          <tbody>
            <tr v-for="w in buy" :key="w.id">
              <td><strong>{{ w.ticker }}</strong></td>
              <td>
                <span class="badge kind-toggle" :class="kindBadge(w.kind)"
                      @click="setKind(w, w.kind === 'Invest' ? 'Trade' : 'Invest')"
                      title="Click to toggle Trade/Invest">{{ w.kind }}</span>
              </td>
              <td class="num row-actions">
                <button class="btn-ghost sm" @click="moveTo(w, 'HELD')" title="You bought it — watch to add/sell too">Now holding →</button>
                <button class="icon-btn danger" @click="remove(w)" title="Remove">✕</button>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="empty">No buy watches. Add one below, or use “☆ Watch to Buy” in Research.</p>

        <div v-if="seed.buy.length" class="seed-box">
          <span class="text-muted">From research:</span>
          <button v-for="s in seed.buy" :key="s.ticker" class="pill" @click="addSeed(s.ticker, 'BUY', s.kind)">
            + {{ s.ticker }} <span class="text-muted">{{ s.kind }}</span>
          </button>
        </div>
      </div>

      <!-- HELD list -->
      <div class="card">
        <div class="card-head">
          <h3>Held</h3>
          <span class="text-muted">watching to ADD or SELL</span>
        </div>
        <table v-if="held.length" class="table">
          <thead><tr><th>Ticker</th><th>Kind</th><th></th></tr></thead>
          <tbody>
            <tr v-for="w in held" :key="w.id">
              <td><strong>{{ w.ticker }}</strong></td>
              <td>
                <span class="badge kind-toggle" :class="kindBadge(w.kind)"
                      @click="setKind(w, w.kind === 'Invest' ? 'Trade' : 'Invest')"
                      title="Click to toggle Trade/Invest">{{ w.kind }}</span>
              </td>
              <td class="num row-actions">
                <button class="btn-ghost sm" @click="moveTo(w, 'BUY')" title="Back to buy-only watching">← Back to Buy</button>
                <button class="icon-btn danger" @click="remove(w)" title="Remove">✕</button>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="empty">No held watches. Move a Buy ticker here once you own it.</p>

        <div v-if="seed.held.length" class="seed-box">
          <span class="text-muted">From open trades:</span>
          <button v-for="t in seed.held" :key="t" class="pill" @click="addSeed(t, 'HELD', 'Trade')">+ {{ t }}</button>
        </div>
      </div>
    </div>

    <!-- Add row -->
    <div class="card add-card">
      <div class="add-row">
        <input type="text" class="ticker-input" v-model="addForm.ticker" placeholder="TICKER" @keyup.enter="addWatch">
        <div class="seg">
          <button :class="{ on: addForm.bucket === 'BUY' }" @click="addForm.bucket = 'BUY'">Buy</button>
          <button :class="{ on: addForm.bucket === 'HELD' }" @click="addForm.bucket = 'HELD'">Held</button>
        </div>
        <div class="seg">
          <button :class="{ on: addForm.kind === 'Trade' }" @click="addForm.kind = 'Trade'">Trade</button>
          <button :class="{ on: addForm.kind === 'Invest' }" @click="addForm.kind = 'Invest'">Invest</button>
        </div>
        <button class="btn-primary" :disabled="!addForm.ticker.trim()" @click="addWatch">Add ticker</button>
      </div>
    </div>

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
      <div class="card-head">
        <h3>Signal now</h3>
        <span class="text-muted">latest closed bar — ignores dedupe, sends nothing</span>
        <div class="spacer"></div>
        <button class="btn-ghost sm" :disabled="loadingNow" @click="loadNow">
          {{ loadingNow ? 'Loading…' : (now ? '↻ Refresh' : 'Show current signals') }}
        </button>
      </div>

      <ul v-if="now && now.length" class="mini-list">
        <li v-for="r in now" :key="r.ticker" class="mini-row" tabindex="0"
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
      <p v-else class="empty">Press “Show current signals” to evaluate every watched ticker against the latest closed bar.</p>

      <p v-if="now && now.length" class="text-muted sig-note">Tap a ticker for prices, RSI and stochastics.</p>
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
            <span class="text-red">never sent</span> means the ticker was armed past that bar (removing and re-adding a ticker no longer does this).
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
