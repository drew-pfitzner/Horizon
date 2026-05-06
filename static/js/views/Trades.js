import { get, post, put, del, isoToday, fmtDate, fmtMoney, fmtPct, fmtNum } from "../utils.js";

const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

export const Trades = {
  data() {
    return {
      tab: "log",
      trades: [],
      perf: null,
      year: new Date().getFullYear(),
      modalMode: null,   // 'new' | 'edit' | 'exit' | null
      form: this._emptyTrade(),
      saving: false,
      message: null,
      messageClass: "",
      pendingDelete: null,
    };
  },
  async mounted() {
    await Promise.all([this.loadTrades(), this.loadPerf()]);
    const q = this.$route.query;
    if (q.new === "1") {
      this.modalMode = "new";
      this.form = {
        ...this._emptyTrade(),
        ticker: q.ticker || "",
        company_name: q.company || "",
        strategy: q.strategy || "TRADE",
        entry_price: q.price ? Number(q.price) : null,
        position_size_pct: q.position ? Number(q.position) : null,
      };
    }
  },
  watch: {
    year() { this.loadPerf(); },
  },
  computed: {
    sortedTrades() {
      return [...this.trades].sort((a, b) => {
        const aOpen = !a.exit_date, bOpen = !b.exit_date;
        if (aOpen !== bOpen) return aOpen ? -1 : 1;
        return (b.entry_date || "").localeCompare(a.entry_date || "");
      });
    },
    monthsList() { return MONTHS; },
  },
  methods: {
    _emptyTrade() {
      return {
        id: null, ticker: "", company_name: "", sector: "", industry: "",
        strategy: "TRADE", currency: "USD",
        entry_date: isoToday(), entry_price: null, shares: null, position_size_pct: null,
        exit_date: null, exit_price: null,
        notes: "",
      };
    },
    async loadTrades() {
      try { this.trades = await get("/api/trades"); } catch (e) { console.error(e); }
    },
    async loadPerf() {
      try { this.perf = await get(`/api/trades/performance?year=${this.year}`); } catch (e) { console.error(e); }
    },
    openNew() { this.modalMode = "new"; this.form = this._emptyTrade(); },
    openEdit(t) { this.modalMode = "edit"; this.form = { ...this._emptyTrade(), ...t }; },
    openExit(t) {
      this.modalMode = "exit";
      this.form = { ...this._emptyTrade(), ...t, exit_date: t.exit_date || isoToday() };
    },
    closeModal() { this.modalMode = null; this.message = null; },
    payload() {
      const p = { ...this.form };
      ["entry_price", "shares", "position_size_pct", "exit_price"].forEach(k => {
        if (p[k] === "" || p[k] == null) p[k] = null;
        else p[k] = Number(p[k]);
      });
      p.ticker = (p.ticker || "").toUpperCase();
      return p;
    },
    async save() {
      if (!this.form.ticker) { this.message = "Ticker required"; this.messageClass = "text-red"; return; }
      this.saving = true;
      this.message = null;
      try {
        if (this.form.id) {
          await put(`/api/trades/${this.form.id}`, this.payload());
        } else {
          await post("/api/trades", this.payload());
        }
        this.message = "Saved";
        this.messageClass = "text-green";
        await Promise.all([this.loadTrades(), this.loadPerf()]);
        setTimeout(() => this.closeModal(), 600);
      } catch (e) {
        this.message = `Error: ${e.message}`;
        this.messageClass = "text-red";
      } finally {
        this.saving = false;
      }
    },
    askDelete(t) { this.pendingDelete = t; },
    cancelDelete() { this.pendingDelete = null; },
    async confirmDelete() {
      const t = this.pendingDelete;
      if (!t) return;
      try {
        await del(`/api/trades/${t.id}`);
        this.pendingDelete = null;
        await Promise.all([this.loadTrades(), this.loadPerf()]);
      } catch (e) {
        alert(e.message);
        this.pendingDelete = null;
      }
    },
    winLossClass(s) {
      if (s === "WIN") return "badge green";
      if (s === "LOSS") return "badge red";
      return "badge";
    },
    monthCell(month) {
      if (!this.perf) return null;
      return this.perf.months.find(m => m.month === month);
    },
  },
  template: `
    <div>
      <div class="toolbar">
        <h1 style="margin: 0;">Trades</h1>
        <div class="spacer"></div>
        <button class="btn-primary" @click="openNew">+ Log Trade</button>
      </div>

      <div class="subtabs">
        <button :class="{ active: tab === 'log' }" @click="tab = 'log'">Trade Log</button>
        <button :class="{ active: tab === 'perf' }" @click="tab = 'perf'">Performance</button>
      </div>

      <div v-if="tab === 'log'">
        <div class="card" v-if="sortedTrades.length">
          <table class="table">
            <thead>
              <tr>
                <th>Ticker</th><th>Strat</th><th>Cur</th>
                <th>Entry</th><th class="num">Px In</th><th class="num">Shares</th><th class="num">Pos %</th>
                <th>Exit</th><th class="num">Px Out</th>
                <th class="num">P/L</th><th class="num">ROI</th><th>W/L</th><th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="t in sortedTrades" :key="t.id" class="clickable" @click="openEdit(t)">
                <td>
                  <strong>{{ t.ticker }}</strong>
                  <div class="text-muted" style="font-size: 0.8rem;">{{ t.company_name }}</div>
                </td>
                <td><span class="badge">{{ t.strategy }}</span></td>
                <td><span class="badge">{{ t.currency || 'USD' }}</span></td>
                <td>{{ fmtDate(t.entry_date) }}</td>
                <td class="num">{{ fmtMoney(t.entry_price) }}</td>
                <td class="num">{{ fmtNum(t.shares, 0) }}</td>
                <td class="num">{{ t.position_size_pct ? t.position_size_pct + '%' : '—' }}</td>
                <td>{{ t.exit_date ? fmtDate(t.exit_date) : '—' }}</td>
                <td class="num">{{ fmtMoney(t.exit_price) }}</td>
                <td class="num" :class="{ 'text-green': t.pl_dollar > 0, 'text-red': t.pl_dollar < 0 }">
                  {{ fmtMoney(t.pl_dollar) }}
                </td>
                <td class="num" :class="{ 'text-green': t.roi_pct > 0, 'text-red': t.roi_pct < 0 }">
                  {{ t.roi_pct != null ? t.roi_pct.toFixed(2) + '%' : '—' }}
                </td>
                <td><span :class="winLossClass(t.win_loss)">{{ t.win_loss || 'HOLD' }}</span></td>
                <td>
                  <button v-if="!t.exit_date" class="btn-ghost" @click.stop="openExit(t)" title="Log exit">↗</button>
                  <button class="btn-danger" @click.stop="askDelete(t)" title="Delete">Delete</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="empty" v-else>No trades yet. Click "+ Log Trade" to start.</div>
      </div>

      <div v-if="tab === 'perf' && perf">
        <div class="card">
          <div class="toolbar">
            <label style="margin: 0;">Year:</label>
            <input type="number" v-model.number="year" style="width: 100px;">
          </div>

          <div class="grid-4">
            <div class="stat">
              <div class="label">Open</div>
              <div class="value">{{ perf.overall.open }}</div>
            </div>
            <div class="stat">
              <div class="label">Closed</div>
              <div class="value">{{ perf.overall.closed }}</div>
            </div>
            <div class="stat">
              <div class="label">Win Rate</div>
              <div class="value">{{ perf.overall.win_rate }}%</div>
            </div>
            <div class="stat">
              <div class="label">Avg ROI</div>
              <div class="value" :class="{ 'text-green': perf.overall.avg_roi > 0, 'text-red': perf.overall.avg_roi < 0 }">
                {{ perf.overall.avg_roi }}%
              </div>
            </div>
          </div>

          <h3 style="margin-top: 1rem;">{{ perf.year }} by Month</h3>
          <table class="table">
            <thead>
              <tr>
                <th>Month</th><th class="num">Opened</th><th class="num">Closed</th>
                <th class="num">Wins</th><th class="num">Losses</th>
                <th class="num">P/L</th><th class="num">ROI</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(m, i) in perf.months" :key="m.month">
                <td>{{ monthsList[i] }}</td>
                <td class="num">{{ m.open_count }}</td>
                <td class="num">{{ m.closed_count }}</td>
                <td class="num text-green">{{ m.wins }}</td>
                <td class="num text-red">{{ m.losses }}</td>
                <td class="num" :class="{ 'text-green': m.total_pl > 0, 'text-red': m.total_pl < 0 }">
                  {{ fmtMoney(m.total_pl) }}
                </td>
                <td class="num" :class="{ 'text-green': m.total_roi > 0, 'text-red': m.total_roi < 0 }">
                  {{ m.total_roi.toFixed(2) }}%
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div v-if="modalMode" class="modal-backdrop" @click.self="closeModal">
        <div class="modal">
          <h2>
            <span v-if="modalMode === 'new'">Log Trade</span>
            <span v-else-if="modalMode === 'exit'">Log Exit — {{ form.ticker }}</span>
            <span v-else>Edit Trade — {{ form.ticker }}</span>
          </h2>

          <div class="grid-2">
            <div class="field">
              <label>Ticker</label>
              <input type="text" v-model="form.ticker">
            </div>
            <div class="field">
              <label>Company</label>
              <input type="text" v-model="form.company_name">
            </div>
            <div class="field">
              <label>Sector</label>
              <input type="text" v-model="form.sector">
            </div>
            <div class="field">
              <label>Industry</label>
              <input type="text" v-model="form.industry">
            </div>
            <div class="field">
              <label>Strategy</label>
              <select v-model="form.strategy">
                <option value="TRADE">Trade</option>
                <option value="INVEST">Invest</option>
              </select>
            </div>
            <div class="field">
              <label>Currency</label>
              <select v-model="form.currency">
                <option value="USD">USD</option>
                <option value="AUD">AUD</option>
              </select>
            </div>
            <div class="field">
              <label>Position Size %</label>
              <input type="number" step="0.01" v-model.number="form.position_size_pct">
            </div>
            <div class="field">
              <label>Entry Date</label>
              <input type="date" v-model="form.entry_date">
            </div>
            <div class="field">
              <label>Entry Price</label>
              <input type="number" step="0.0001" v-model.number="form.entry_price">
            </div>
            <div class="field">
              <label>Shares</label>
              <input type="number" step="0.0001" v-model.number="form.shares">
            </div>
            <div class="field">
              <label>Exit Date</label>
              <input type="date" v-model="form.exit_date">
            </div>
            <div class="field">
              <label>Exit Price</label>
              <input type="number" step="0.0001" v-model.number="form.exit_price">
            </div>
          </div>
          <div class="field">
            <label>Notes</label>
            <textarea v-model="form.notes"></textarea>
          </div>

          <div class="modal-actions">
            <span :class="messageClass" style="margin-right: auto;">{{ message }}</span>
            <button @click="closeModal">Cancel</button>
            <button class="btn-primary" :disabled="saving" @click="save">
              {{ saving ? 'Saving...' : 'Save' }}
            </button>
          </div>
        </div>
      </div>

      <div class="modal-backdrop" v-if="pendingDelete" @click.self="cancelDelete">
        <div class="modal">
          <h3>Delete trade?</h3>
          <p>This will permanently remove the trade entry for <strong>{{ pendingDelete.ticker }}</strong>.</p>
          <div class="toolbar">
            <button class="btn-danger" @click="confirmDelete">Delete</button>
            <button class="btn-ghost" @click="cancelDelete">Cancel</button>
          </div>
        </div>
      </div>
    </div>
  `,
  setup() { return { fmtDate, fmtMoney, fmtPct, fmtNum }; },
};
