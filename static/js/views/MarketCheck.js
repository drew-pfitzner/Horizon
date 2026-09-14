import { get, post, del, isoToday, fmtDate, fmtCcy, fxRate, sortRows, toggleSortState } from "../utils.js";

const QUOTE_CCY = "USD"; // secondary display currency

export const MarketCheck = {
  emits: ["gate-updated"],
  data() {
    return {
      form: {
        date: isoToday(),
        st_louis_fed: null, vix: null,
        rsi: null, stochastic: null, s5fi: null, fear_greed: null,
        notes: "",
      },
      preview: null,
      saving: false,
      message: null,
      messageClass: "",
      history: [],
      pendingDelete: null,
      historySort: { key: "date", dir: "desc" },
      fetching: false,
      live: null,          // per-field {value, source, as_of, error} from the last fetch
      liveError: null,
      s5fiStatus: null,    // 'computing' while the background rebuild runs
      s5fiProgress: null,
      portfolio: { value: 0, currency: "AUD" },
      fxRates: {},
    };
  },
  computed: {
    sortedHistory() { return sortRows(this.history, this.historySort.key, this.historySort.dir); },
    baseCcy() { return (this.portfolio.currency || "AUD").toUpperCase(); },
    quoteCcy() { return QUOTE_CCY; },
    showQuote() { return this.baseCcy !== this.quoteCcy; },
    baseToQuoteRate() { return fxRate(this.fxRates, this.baseCcy, this.quoteCcy); },
    // Preview position size (%) → dollar amount in the portfolio's base currency
    // and the USD quote, mirroring the Home banner.
    sizePct() {
      const p = this.preview && this.preview.position_size_pct;
      return p != null ? Number(p) : null;
    },
    sizeInBase() {
      if (this.sizePct == null || !this.portfolio.value) return null;
      return this.portfolio.value * this.sizePct / 100;
    },
    sizeInQuote() {
      if (this.sizeInBase == null || this.baseToQuoteRate == null) return null;
      return this.sizeInBase * this.baseToQuoteRate;
    },
    stlColor() {
      const v = this.form.st_louis_fed;
      if (v == null || v === "") return "muted";
      if (v <= -1) return "green";
      if (v < 0) return "blue";
      if (v < 1) return "orange";
      return "red";
    },
    vixColor() {
      const v = this.form.vix;
      if (v == null || v === "") return "muted";
      if (v <= 25) return "green";
      if (v < 30) return "orange";
      return "red";
    },
    rsiColor() { return this._scoreColor(this.form.rsi, 30, 60); },
    stoColor() { return this._scoreColor(this.form.stochastic, 20, 80); },
    s5fiColor() { return this._scoreColor(this.form.s5fi, 40, 70); },
    fgColor() { return this._scoreColor(this.form.fear_greed, 45, 55); },
    canSave() {
      return ["st_louis_fed", "vix", "rsi", "stochastic", "s5fi", "fear_greed"]
        .every(k => this.form[k] !== null && this.form[k] !== "");
    },
  },
  watch: {
    form: { deep: true, handler() { this.recompute(); } },
  },
  methods: {
    sortHistory(col) { toggleSortState(this.historySort, col); },
    _scoreColor(v, low, mid) {
      if (v == null || v === "") return "muted";
      if (v <= low) return "green";
      if (v < mid) return "orange";
      return "red";
    },
    dotStyle(color) {
      const map = {
        green: "var(--green)", red: "var(--red)", orange: "var(--orange)",
        blue: "var(--blue)", muted: "var(--text-2)",
      };
      return { background: map[color] || "var(--text-2)" };
    },
    async recompute() {
      const payload = { ...this.form };
      ["st_louis_fed", "vix", "rsi", "stochastic", "s5fi", "fear_greed"].forEach(k => {
        if (payload[k] === "") payload[k] = null;
        else if (payload[k] != null) payload[k] = Number(payload[k]);
      });
      try {
        this.preview = await post("/api/market-check/preview", payload);
      } catch (e) {
        this.preview = null;
      }
    },
    async save() {
      if (!this.canSave) return;
      this.saving = true;
      this.message = null;
      try {
        const payload = { ...this.form };
        ["st_louis_fed", "vix", "rsi", "stochastic", "s5fi", "fear_greed"].forEach(k => {
          payload[k] = payload[k] == null || payload[k] === "" ? null : Number(payload[k]);
        });
        await post("/api/market-check", payload);
        this.message = "Saved";
        this.messageClass = "text-green";
        this.$emit("gate-updated");
        await this.loadHistory();
      } catch (e) {
        this.message = `Error: ${e.message}`;
        this.messageClass = "text-red";
      } finally {
        this.saving = false;
        setTimeout(() => { this.message = null; }, 3000);
      }
    },
    // Pull all six indicators from their public sources. RSI/Stochastic are
    // computed from S&P 500 bars by the same engine the alerts use, so they
    // match the TradingView panes; S5FI is rebuilt from the constituents and
    // takes a minute, so a stale one is refreshed in the background.
    async fetchLive() {
      this.fetching = true;
      this.liveError = null;
      try {
        const snap = await get("/api/market-data/snapshot");
        this.applyLive(snap);
        if (!snap.s5fi || snap.s5fi.stale) await this.refreshS5fi();
      } catch (e) {
        this.liveError = e.message;
      } finally {
        this.fetching = false;
      }
    },
    applyLive(snap) {
      this.live = snap;
      ["st_louis_fed", "vix", "rsi", "stochastic", "s5fi", "fear_greed"].forEach(k => {
        const f = snap[k];
        if (f && f.value != null) this.form[k] = f.value;
      });
    },
    async refreshS5fi() {
      this.s5fiStatus = "computing";
      try {
        await post("/api/market-data/s5fi/refresh", {});
      } catch (e) {
        // 409 just means a rebuild is already in flight — poll that one.
        if (!/already computing/i.test(e.message)) {
          this.s5fiStatus = null;
          this.liveError = e.message;
          return;
        }
      }
      this.pollS5fi();
    },
    async pollS5fi() {
      try {
        const st = await get("/api/market-data/s5fi/status");
        if (st.status === "running") {
          this.s5fiProgress = st.output.length ? st.output[st.output.length - 1] : null;
          setTimeout(() => this.pollS5fi(), 4000);
          return;
        }
        this.s5fiStatus = null;
        this.s5fiProgress = null;
        if (st.status === "error") {
          this.liveError = `S5FI: ${st.error}`;
        } else if (st.result && st.result.value != null) {
          this.form.s5fi = st.result.value;
          if (this.live) this.live.s5fi = { ...st.result, source: "computed" };
        }
      } catch (e) {
        this.s5fiStatus = null;
        this.liveError = e.message;
      }
    },
    liveInfo(key) {
      const f = this.live && this.live[key];
      if (!f) return null;
      if (f.error) return f.error;
      const bits = [f.source];
      if (f.as_of) bits.push(fmtDate(f.as_of));
      if (key === "stochastic" && f.k != null) bits.push(`%K ${f.k}`);
      if (key === "fear_greed" && f.rating) bits.push(f.rating);
      return bits.join(" · ");
    },
    async loadHistory() {
      try {
        this.history = await get("/api/market-check/history?limit=14");
      } catch (e) { console.error(e); }
    },
    loadFromHistory(row) {
      this.form = {
        date: row.date,
        st_louis_fed: row.st_louis_fed, vix: row.vix,
        rsi: row.rsi, stochastic: row.stochastic, s5fi: row.s5fi, fear_greed: row.fear_greed,
        notes: row.notes || "",
      };
      window.scrollTo({ top: 0, behavior: "smooth" });
    },
    askDelete(row) {
      this.pendingDelete = row;
    },
    cancelDelete() {
      this.pendingDelete = null;
    },
    async confirmDelete() {
      const row = this.pendingDelete;
      if (!row) return;
      try {
        await del(`/api/market-check/${row.date}`);
        this.pendingDelete = null;
        await this.loadHistory();
        this.$emit("gate-updated");
        this.message = `Deleted ${row.date}`;
        this.messageClass = "text-green";
        setTimeout(() => { this.message = null; }, 3000);
      } catch (e) {
        this.message = `Error: ${e.message}`;
        this.messageClass = "text-red";
        this.pendingDelete = null;
      }
    },
    riskLabel(r) {
      if (r === "OK") return "OK";
      if (r === "CAUTION") return "CAUTION";
      if (r === "NO_TRADE") return "NO TRADE";
      return "—";
    },
    riskClass(r) {
      if (r === "OK") return "badge green";
      if (r === "CAUTION") return "badge orange";
      if (r === "NO_TRADE") return "badge red";
      return "badge";
    },
    sizeBadge(level) {
      if (level === "LOW") return "badge green";
      if (level === "MED") return "badge orange";
      if (level === "HIGH") return "badge red";
      return "badge";
    },
  },
  async mounted() {
    try {
      const today = await get(`/api/market-check/today?date=${isoToday()}`);
      if (today) {
        this.form = {
          date: today.date,
          st_louis_fed: today.st_louis_fed, vix: today.vix,
          rsi: today.rsi, stochastic: today.stochastic,
          s5fi: today.s5fi, fear_greed: today.fear_greed,
          notes: today.notes || "",
        };
      }
    } catch (e) { console.error(e); }
    try {
      const [portfolio, fx] = await Promise.all([
        get("/api/settings/portfolio"),
        get("/api/settings/fx-rates"),
      ]);
      this.portfolio = { value: Number(portfolio.value) || 0, currency: portfolio.currency || "AUD" };
      this.fxRates = fx || {};
    } catch (e) { console.error(e); }
    await this.recompute();
    await this.loadHistory();
  },
  template: `
    <div>
      <h1>Market Check</h1>

      <div v-if="preview && preview.position_size_level" class="position-banner">
        <div class="position-banner-label">Position Size</div>
        <span :class="sizeBadge(preview.position_size_level)">
          {{ preview.position_size_level }} — {{ preview.position_size_pct }}%
        </span>
        <div v-if="sizeInBase != null" class="position-banner-amounts">
          {{ fmtCcy(sizeInBase, baseCcy) }} {{ baseCcy }}<template v-if="showQuote && sizeInQuote != null"> · ≈ {{ fmtCcy(sizeInQuote, quoteCcy) }} {{ quoteCcy }}</template>
          <span v-if="showQuote && baseToQuoteRate != null" class="text-muted">&nbsp;({{ quoteCcy }}/{{ baseCcy }} @ {{ baseToQuoteRate.toFixed(4) }})</span>
        </div>
      </div>

      <div class="toolbar">
        <button :disabled="fetching" @click="fetchLive">
          {{ fetching ? "Fetching..." : "Fetch live data" }}
        </button>
        <span v-if="s5fiStatus === 'computing'" class="text-muted">
          Rebuilding S5FI from the 500 constituents (a minute or two)<template v-if="s5fiProgress"> — {{ s5fiProgress }}</template>
        </span>
        <span v-if="liveError" class="text-red">{{ liveError }}</span>
      </div>

      <div class="grid-2">
        <div class="card">
          <h3>Crash / Recession</h3>
          <div class="field">
            <label>St. Louis Fed Index</label>
            <div class="input-with-status">
              <span class="status-dot" :style="dotStyle(stlColor)"></span>
              <input type="number" step="0.0001" v-model.number="form.st_louis_fed">
            </div>
            <small class="text-muted">≤ -1 green · &lt; 0 blue · &lt; 1 orange · ≥ 1 red</small>
            <small v-if="liveInfo('st_louis_fed')" class="text-muted live-source">{{ liveInfo('st_louis_fed') }}</small>
          </div>
          <div class="field">
            <label>VIX</label>
            <div class="input-with-status">
              <span class="status-dot" :style="dotStyle(vixColor)"></span>
              <input type="number" step="0.01" v-model.number="form.vix">
            </div>
            <small class="text-muted">≤ 25 green · &lt; 30 orange · ≥ 30 red</small>
            <small v-if="liveInfo('vix')" class="text-muted live-source">{{ liveInfo('vix') }}</small>
          </div>
          <div v-if="preview" class="field">
            <label>Market Risk</label>
            <span :class="riskClass(preview.crash_risk)">{{ riskLabel(preview.crash_risk) }}</span>
          </div>
        </div>

        <div class="card">
          <h3>Pullback / Correction</h3>
          <div class="field">
            <label>RSI</label>
            <div class="input-with-status">
              <span class="status-dot" :style="dotStyle(rsiColor)"></span>
              <input type="number" step="0.01" v-model.number="form.rsi">
            </div>
            <small class="text-muted">≤ 30 LOW · &lt; 60 MED · ≥ 60 HIGH</small>
            <small v-if="liveInfo('rsi')" class="text-muted live-source">{{ liveInfo('rsi') }}</small>
          </div>
          <div class="field">
            <label>Stochastic</label>
            <div class="input-with-status">
              <span class="status-dot" :style="dotStyle(stoColor)"></span>
              <input type="number" step="0.01" v-model.number="form.stochastic">
            </div>
            <small class="text-muted">≤ 20 LOW · &lt; 80 MED · ≥ 80 HIGH</small>
            <small v-if="liveInfo('stochastic')" class="text-muted live-source">{{ liveInfo('stochastic') }}</small>
          </div>
          <div class="field">
            <label>S&P 500 % Above 50DMA (S5FI)</label>
            <div class="input-with-status">
              <span class="status-dot" :style="dotStyle(s5fiColor)"></span>
              <input type="number" step="0.01" v-model.number="form.s5fi">
            </div>
            <small class="text-muted">≤ 40 LOW · &lt; 70 MED · ≥ 70 HIGH</small>
            <small v-if="liveInfo('s5fi')" class="text-muted live-source">{{ liveInfo('s5fi') }}</small>
          </div>
          <div class="field">
            <label>Fear &amp; Greed</label>
            <div class="input-with-status">
              <span class="status-dot" :style="dotStyle(fgColor)"></span>
              <input type="number" step="0.01" v-model.number="form.fear_greed">
            </div>
            <small class="text-muted">≤ 45 LOW · &lt; 55 MED · ≥ 55 HIGH</small>
            <small v-if="liveInfo('fear_greed')" class="text-muted live-source">{{ liveInfo('fear_greed') }}</small>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="field">
          <label>Notes</label>
          <textarea v-model="form.notes" placeholder="Anything to remember about today..."></textarea>
        </div>
        <div class="field">
          <label>Date</label>
          <input type="date" v-model="form.date">
        </div>
        <div class="toolbar">
          <button class="btn-primary" :disabled="!canSave || saving" @click="save">
            {{ saving ? "Saving..." : "Save" }}
          </button>
          <span :class="messageClass">{{ message }}</span>
        </div>
      </div>

      <div class="card">
        <h3>History (last 14)</h3>
        <div class="table-wrap" v-if="history.length"><table class="table">
          <thead>
            <tr>
              <sort-th col="date" :sort="historySort" @sort="sortHistory">Date</sort-th>
              <sort-th col="st_louis_fed" :sort="historySort" @sort="sortHistory" :num="true">STL</sort-th>
              <sort-th col="vix" :sort="historySort" @sort="sortHistory" :num="true">VIX</sort-th>
              <sort-th col="rsi" :sort="historySort" @sort="sortHistory" :num="true">RSI</sort-th>
              <sort-th col="stochastic" :sort="historySort" @sort="sortHistory" :num="true">STO</sort-th>
              <sort-th col="s5fi" :sort="historySort" @sort="sortHistory" :num="true">S5FI</sort-th>
              <sort-th col="fear_greed" :sort="historySort" @sort="sortHistory" :num="true">F/G</sort-th>
              <sort-th col="crash_risk" :sort="historySort" @sort="sortHistory">Risk</sort-th>
              <sort-th col="position_size_level" :sort="historySort" @sort="sortHistory">Size</sort-th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in sortedHistory" :key="row.date" class="clickable">
              <td @click="loadFromHistory(row)">{{ fmtDate(row.date) }}</td>
              <td class="num" @click="loadFromHistory(row)">{{ row.st_louis_fed }}</td>
              <td class="num" @click="loadFromHistory(row)">{{ row.vix }}</td>
              <td class="num" @click="loadFromHistory(row)">{{ row.rsi }}</td>
              <td class="num" @click="loadFromHistory(row)">{{ row.stochastic }}</td>
              <td class="num" @click="loadFromHistory(row)">{{ row.s5fi }}</td>
              <td class="num" @click="loadFromHistory(row)">{{ row.fear_greed }}</td>
              <td @click="loadFromHistory(row)"><span :class="riskClass(row.crash_risk)">{{ riskLabel(row.crash_risk) }}</span></td>
              <td @click="loadFromHistory(row)"><span :class="sizeBadge(row.position_size_level)" v-if="row.position_size_level">{{ row.position_size_level }}</span></td>
              <td><button class="btn-danger" @click.stop="askDelete(row)">Delete</button></td>
            </tr>
          </tbody>
        </table></div>
        <div class="empty" v-else>No history yet — save your first check above.</div>
      </div>

      <div class="modal-backdrop" v-if="pendingDelete" @click.self="cancelDelete">
        <div class="modal">
          <h3>Delete market check?</h3>
          <p>This will permanently remove the entry for <strong>{{ fmtDate(pendingDelete.date) }}</strong>.</p>
          <div class="toolbar">
            <button class="btn-danger" @click="confirmDelete">Delete</button>
            <button class="btn-ghost" @click="cancelDelete">Cancel</button>
          </div>
        </div>
      </div>
    </div>
  `,
  setup() { return { fmtDate, fmtCcy }; },
};
