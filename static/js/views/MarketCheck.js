import { get, post, del, isoToday, fmtDate, sortRows, toggleSortState } from "../utils.js";

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
    };
  },
  computed: {
    sortedHistory() { return sortRows(this.history, this.historySort.key, this.historySort.dir); },
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
    await this.recompute();
    await this.loadHistory();
  },
  template: `
    <div>
      <h1>Market Check</h1>

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
          </div>
          <div class="field">
            <label>VIX</label>
            <div class="input-with-status">
              <span class="status-dot" :style="dotStyle(vixColor)"></span>
              <input type="number" step="0.01" v-model.number="form.vix">
            </div>
            <small class="text-muted">≤ 25 green · &lt; 30 orange · ≥ 30 red</small>
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
          </div>
          <div class="field">
            <label>Stochastic</label>
            <div class="input-with-status">
              <span class="status-dot" :style="dotStyle(stoColor)"></span>
              <input type="number" step="0.01" v-model.number="form.stochastic">
            </div>
            <small class="text-muted">≤ 20 LOW · &lt; 80 MED · ≥ 80 HIGH</small>
          </div>
          <div class="field">
            <label>S&P 500 % Above 50DMA (S5FI)</label>
            <div class="input-with-status">
              <span class="status-dot" :style="dotStyle(s5fiColor)"></span>
              <input type="number" step="0.01" v-model.number="form.s5fi">
            </div>
            <small class="text-muted">≤ 40 LOW · &lt; 70 MED · ≥ 70 HIGH</small>
          </div>
          <div class="field">
            <label>Fear &amp; Greed</label>
            <div class="input-with-status">
              <span class="status-dot" :style="dotStyle(fgColor)"></span>
              <input type="number" step="0.01" v-model.number="form.fear_greed">
            </div>
            <small class="text-muted">≤ 45 LOW · &lt; 55 MED · ≥ 55 HIGH</small>
          </div>
          <div v-if="preview && preview.position_size_level" class="field">
            <label>Position Size</label>
            <span :class="sizeBadge(preview.position_size_level)">
              {{ preview.position_size_level }} — {{ preview.position_size_pct }}%
            </span>
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
  setup() { return { fmtDate }; },
};
