import { get, post, put, del, fmtDate } from "../utils.js";

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
      try { await del(`/api/alerts/log/${r.id}`); this.log = this.log.filter(x => x.id !== r.id); }
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
    fx(v, digits = 1) { return v == null ? "—" : Number(v).toFixed(digits); },
    kindBadge(kind) { return kind === "Invest" ? "blue" : "green"; },
    actionBadge(a) { return a === "SELL" ? "red" : (a === "ADD" ? "orange" : "green"); },
  },
  setup() { return { fmtDate }; },
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

      <table v-if="now && now.length" class="table">
        <thead><tr>
          <th>Ticker</th><th>List</th><th>Bar</th><th class="num">Price</th>
          <th class="num">RSI</th><th class="num">%K</th><th class="num">%D</th>
          <th>Now</th><th>Last signal</th>
        </tr></thead>
        <tbody>
          <tr v-for="r in now" :key="r.ticker">
            <td><strong>{{ r.ticker }}</strong></td>
            <td>{{ r.bucket }}</td>
            <td class="text-muted">{{ r.bar_date || '—' }}</td>
            <td class="num">{{ fx(r.close, 2) }}</td>
            <td class="num">{{ fx(r.rsi) }}</td>
            <td class="num">{{ fx(r.k) }}</td>
            <td class="num">{{ fx(r.d) }}</td>
            <td>
              <span v-if="r.error" class="text-red" :title="r.error">error</span>
              <span v-else-if="r.action" class="badge" :class="actionBadge(r.action)">{{ r.action }}</span>
              <span v-else class="text-muted">—</span>
            </td>
            <td>
              <template v-if="r.last_signal">
                <span class="badge" :class="actionBadge(r.last_signal.action)">{{ r.last_signal.action }}</span>
                <span class="text-muted"> {{ r.last_signal.date }} · </span>
                <span :class="deliveryClass(r.last_signal.delivery)"
                      :title="r.last_signal.delivery === 'missed' ? 'The watermark was already past this bar when it was evaluated — no push was ever sent for it.' : ''">
                  {{ deliveryLabel(r.last_signal.delivery) }}
                </span>
              </template>
              <span v-else class="text-muted">none in 2y</span>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else-if="now" class="empty">No active watches.</p>
      <p v-else class="empty">Press “Show current signals” to evaluate every watched ticker against the latest closed bar.</p>

      <p v-if="now && now.length" class="text-muted sig-note">
        “Now” is an edge on the latest closed bar, so it clears the day after it fires — “Last signal” is the one to read.
        <span class="text-red">never sent</span> means the ticker was armed past that bar (removing and re-adding a ticker no longer does this).
      </p>
    </div>

    <!-- Recent alerts -->
    <div class="card">
      <div class="card-head">
        <h3>Recent alerts</h3>
        <div class="spacer"></div>
        <button v-if="log.length" class="btn-ghost sm" @click="clearLog">Clear all</button>
      </div>
      <table v-if="log.length" class="table">
        <thead><tr><th>When</th><th>Ticker</th><th>List</th><th>Action</th><th>Bar</th><th class="num">Price</th><th>Status</th><th></th></tr></thead>
        <tbody>
          <tr v-for="r in log" :key="r.id">
            <td class="text-muted">{{ fmtDate(r.sent_at) }}</td>
            <td><strong>{{ r.ticker }}</strong></td>
            <td>{{ r.bucket || '—' }}</td>
            <td><span v-if="r.action" class="badge" :class="actionBadge(r.action)">{{ r.action }}</span><span v-else>—</span></td>
            <td>{{ r.bar_date || '—' }}</td>
            <td class="num">{{ r.price != null ? r.price.toFixed(2) : '—' }}</td>
            <td>
              <span v-if="r.ok" class="text-muted">sent</span>
              <span v-else class="text-red" :title="r.error">failed</span>
            </td>
            <td class="num"><button class="icon-btn danger" @click="deleteLogEntry(r)" title="Remove from history">✕</button></td>
          </tr>
        </tbody>
      </table>
      <p v-else class="empty">No alerts yet.</p>
    </div>
  </div>
  `,
};
