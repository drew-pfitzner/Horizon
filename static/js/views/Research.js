import { get, post, put, del, isoToday, fmtDate, decisionClass, assessmentClass, statusClass, fmtPct, fmtMoney } from "../utils.js";

const FUND_FIELDS = [
  ["f_roa", "ROA > 8%"],
  ["f_roe", "ROE > 12%"],
  ["f_roi", "ROI > 8%"],
  ["f_npm", "Net Profit Margin > 0%"],
  ["f_eps_5yr", "EPS Growth Past 5 Yrs > 0%"],
  ["f_eps_1yr", "EPS Growth Past Yr > 0%"],
  ["f_eps_next", "EPS Growth Next Yr > 0%"],
  ["f_sales_5yr", "Sales Growth Past 5 Yrs > 0%"],
  ["f_current_ratio", "Current Ratio > 1"],
  ["f_debt_equity", "Debt to Equity < 0.4"],
];

export const Research = {
  props: ["id"],
  data() {
    return {
      list: [],
      form: this._emptyForm(),
      mode: "list",   // 'list' | 'edit' | 'new'
      smHolders: null,
      smLoading: false,
      message: null,
      messageClass: "",
      saving: false,
      pendingDelete: null,
    };
  },
  computed: {
    fundFields() { return FUND_FIELDS; },
    fundamentalsScore() {
      return FUND_FIELDS.reduce((acc, [k]) => acc + (this.form[k] ? 1 : 0), 0);
    },
    isEdit() { return this.mode === "edit"; },
    isNew() { return this.mode === "new"; },
  },
  watch: {
    "form.ticker"(v) {
      if (this.mode === "list") return;
      // Don't auto-fetch on every keystroke; rely on blur button
    },
  },
  methods: {
    _emptyForm() {
      const base = {
        id: null, ticker: "", company_name: "",
        date_researched: isoToday(),
        decision: "NO_ACTION",
        notes: "",
      };
      [...FUND_FIELDS.map(x => x[0]),
       "market_cap_ok", "sm_holding_5pct", "sm_top3_increasing",
       "liquidity_ok", "tech_rsi_ok", "tech_sto_ok", "tech_cross_ok",
       "price_below_mos"].forEach(k => base[k] = false);
      return base;
    },
    async loadList() {
      try { this.list = await get("/api/research"); } catch (e) { console.error(e); }
    },
    newForm() {
      this.form = this._emptyForm();
      this.smHolders = null;
      this.mode = "new";
    },
    editForm(row) {
      this.form = { ...this._emptyForm(), ...row };
      Object.keys(this.form).forEach(k => {
        if (typeof row[k] === "number" && (k.startsWith("f_") || k.endsWith("_ok") || k === "price_below_mos" || k === "sm_holding_5pct" || k === "sm_top3_increasing" || k === "market_cap_ok")) {
          this.form[k] = row[k] === 1;
        }
      });
      this.smHolders = null;
      this.mode = "edit";
      this.fetchSmartMoney();
    },
    cancel() { this.mode = "list"; this.smHolders = null; },
    async fetchSmartMoney() {
      const t = (this.form.ticker || "").trim().toUpperCase();
      if (!t) { this.smHolders = null; return; }
      this.smLoading = true;
      try {
        const data = await get(`/api/smart-money/query/${t}?limit=10`);
        this.smHolders = data;
      } catch (e) {
        console.error(e);
        this.smHolders = null;
      } finally { this.smLoading = false; }
    },
    payload() {
      const p = { ...this.form };
      Object.keys(p).forEach(k => {
        if (typeof p[k] === "boolean") p[k] = p[k] ? 1 : 0;
      });
      p.ticker = (p.ticker || "").toUpperCase();
      return p;
    },
    async save() {
      if (!this.form.ticker) { this.message = "Ticker required"; this.messageClass = "text-red"; return; }
      this.saving = true;
      try {
        let data;
        if (this.mode === "edit" && this.form.id) {
          data = await put(`/api/research/${this.form.id}`, this.payload());
        } else {
          data = await post("/api/research", this.payload());
        }
        this.message = "Saved";
        this.messageClass = "text-green";
        await this.loadList();
        this.editForm(data);
      } catch (e) {
        this.message = `Error: ${e.message}`;
        this.messageClass = "text-red";
      } finally {
        this.saving = false;
        setTimeout(() => { this.message = null; }, 3000);
      }
    },
    askDelete(row) { this.pendingDelete = row; },
    cancelDelete() { this.pendingDelete = null; },
    async confirmDelete() {
      const row = this.pendingDelete;
      if (!row) return;
      try {
        await del(`/api/research/${row.id}`);
        this.pendingDelete = null;
        await this.loadList();
        if (this.form.id === row.id) this.cancel();
      } catch (e) {
        this.message = `Error: ${e.message}`;
        this.messageClass = "text-red";
        this.pendingDelete = null;
      }
    },
    async openValuation() {
      if (!this.form.ticker) { alert("Save the research entry first."); return; }
      this.$router.push(`/valuation/${this.form.ticker.toUpperCase()}`);
    },
  },
  async mounted() {
    await this.loadList();
    if (this.id) {
      const row = this.list.find(r => String(r.id) === String(this.id));
      if (row) this.editForm(row);
    }
  },
  template: `
    <div>
      <div v-if="mode === 'list'">
        <div class="toolbar">
          <h1 style="margin: 0;">Research</h1>
          <div class="spacer"></div>
          <button class="btn-primary" @click="newForm">+ New Research</button>
        </div>
        <div class="card" v-if="list.length">
          <table class="table">
            <thead>
              <tr>
                <th>Ticker</th><th>Date</th><th>Score</th>
                <th>Decision</th><th>Valuation</th><th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in list" :key="r.id" class="clickable" @click="editForm(r)">
                <td><strong>{{ r.ticker }}</strong> <span class="text-muted">{{ r.company_name }}</span></td>
                <td>{{ fmtDate(r.date_researched) }}</td>
                <td><span class="score-pill">{{ r.fundamentals_score }}/10</span></td>
                <td><span :class="decisionClass(r.decision)">{{ r.decision || 'NO_ACTION' }}</span></td>
                <td>
                  <span :class="assessmentClass(r.valuation_assessment)" v-if="r.valuation_assessment">{{ r.valuation_assessment }}</span>
                  <span class="text-muted" v-else>—</span>
                </td>
                <td>
                  <button class="btn-danger" @click.stop="askDelete(r)" title="Delete">Delete</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="empty" v-else>No research yet. Click "New Research" to start.</div>
      </div>

      <div v-else>
        <div class="toolbar">
          <h1 style="margin: 0;">{{ isEdit ? form.ticker + ' — Edit' : 'New Research' }}</h1>
          <div class="spacer"></div>
          <button @click="cancel">← Back</button>
        </div>

        <div class="grid-2">
          <div class="card">
            <h3>Stock</h3>
            <div class="grid-2">
              <div class="field">
                <label>Ticker</label>
                <input type="text" v-model="form.ticker" @blur="fetchSmartMoney" placeholder="AAPL">
              </div>
              <div class="field">
                <label>Company</label>
                <input type="text" v-model="form.company_name">
              </div>
              <div class="field">
                <label>Date Researched</label>
                <input type="date" v-model="form.date_researched">
              </div>
              <div class="field">
                <label>Decision</label>
                <select v-model="form.decision">
                  <option value="NO_ACTION">No Action</option>
                  <option value="TRADE">Trade</option>
                  <option value="INVEST">Invest</option>
                </select>
              </div>
            </div>
          </div>

          <div class="card">
            <h3>Fundamentals — {{ fundamentalsScore }}/10</h3>
            <div class="check-list">
              <label v-for="[key, label] in fundFields" :key="key" class="check-item" :class="{ checked: form[key] }">
                <input type="checkbox" v-model="form[key]">
                <span>{{ label }}</span>
              </label>
            </div>
          </div>

          <div class="card">
            <h3>Company Size, Smart Money, Liquidity</h3>
            <div class="check-list">
              <label class="check-item" :class="{ checked: form.market_cap_ok }">
                <input type="checkbox" v-model="form.market_cap_ok">
                <span>Market Cap &gt; $1B</span>
              </label>
              <label class="check-item" :class="{ checked: form.sm_holding_5pct }">
                <input type="checkbox" v-model="form.sm_holding_5pct">
                <span>SM Holding &gt; 5% ⚠</span>
              </label>
              <label class="check-item" :class="{ checked: form.sm_top3_increasing }">
                <input type="checkbox" v-model="form.sm_top3_increasing">
                <span>Top 3 SM Increasing Stake</span>
              </label>
              <label class="check-item" :class="{ checked: form.liquidity_ok }">
                <input type="checkbox" v-model="form.liquidity_ok">
                <span>Avg Daily Vol &gt; 10× Position</span>
              </label>
            </div>
          </div>

          <div class="card">
            <h3>Technicals</h3>
            <p class="text-muted" style="font-size: 0.8rem; margin: 0 0 0.5rem;">
              Trade: RSI &lt; 35 &amp; UP · STO &lt; 20 · Fast over Slow Cross<br>
              Invest: RSI &lt; 40 &amp; UP · STO &lt; 20 · Fast over Slow Cross
            </p>
            <div class="check-list">
              <label class="check-item" :class="{ checked: form.tech_rsi_ok }">
                <input type="checkbox" v-model="form.tech_rsi_ok">
                <span>RSI in range &amp; trending up</span>
              </label>
              <label class="check-item" :class="{ checked: form.tech_sto_ok }">
                <input type="checkbox" v-model="form.tech_sto_ok">
                <span>STO Slow &lt; 20</span>
              </label>
              <label class="check-item" :class="{ checked: form.tech_cross_ok }">
                <input type="checkbox" v-model="form.tech_cross_ok">
                <span>STO Cross (Fast over Slow)</span>
              </label>
              <label class="check-item" :class="{ checked: form.price_below_mos }">
                <input type="checkbox" v-model="form.price_below_mos">
                <span>Price &lt; MOS (Margin of Safety)</span>
              </label>
            </div>
          </div>
        </div>

        <div class="card">
          <h3>Valuation</h3>
          <div class="toolbar">
            <button @click="openValuation" :disabled="!form.ticker">Open Valuation Calculator →</button>
            <span class="text-muted">Run + save valuation, then return here.</span>
          </div>
        </div>

        <div class="card">
          <h3>Smart Money — {{ form.ticker || 'enter ticker' }} <span class="text-muted" style="font-weight: 400; font-size: 0.8rem;">(top 10 by weight)</span></h3>
          <div class="toolbar">
            <button @click="fetchSmartMoney" :disabled="!form.ticker || smLoading">
              {{ smLoading ? 'Loading...' : 'Refresh' }}
            </button>
            <span class="text-muted" v-if="smHolders && smHolders.quarter">Quarter: {{ smHolders.quarter }}</span>
          </div>
          <div v-if="smHolders && (smHolders.holders.length || smHolders.exited.length)">
            <table class="table">
              <thead>
                <tr><th>Guru</th><th>Firm</th><th class="num">Weight</th><th class="num">Δ Weight</th><th>Status</th></tr>
              </thead>
              <tbody>
                <tr v-for="h in smHolders.holders" :key="h.name">
                  <td>{{ h.name }}</td>
                  <td class="text-muted">{{ h.firm }}</td>
                  <td class="num">{{ h.weight ? h.weight.toFixed(2) + '%' : '—' }}</td>
                  <td class="num" :class="statusClass(h.status)">
                    {{ h.weight_change != null ? (h.weight_change > 0 ? '+' : '') + h.weight_change.toFixed(2) + 'pp' : '—' }}
                  </td>
                  <td><span :class="statusClass(h.status)">{{ h.status }}</span></td>
                </tr>
                <tr v-for="e in smHolders.exited" :key="'x'+e.name">
                  <td>{{ e.name }}</td>
                  <td class="text-muted">{{ e.firm }}</td>
                  <td class="num text-muted">0.00%</td>
                  <td class="num text-red">{{ e.weight_change != null ? e.weight_change.toFixed(2) + 'pp' : '—' }}</td>
                  <td><span class="text-red">Exited</span></td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="empty" v-else-if="smHolders">No gurus hold {{ form.ticker }} this quarter.</div>
          <div class="empty" v-else>Type a ticker and click Refresh.</div>
        </div>

        <div class="card">
          <h3>Notes &amp; Decision</h3>
          <div class="field">
            <label>Notes</label>
            <textarea v-model="form.notes"></textarea>
          </div>
          <div class="toolbar">
            <button class="btn-primary" :disabled="saving" @click="save">
              {{ saving ? 'Saving...' : (isEdit ? 'Update' : 'Create') }}
            </button>
            <span :class="messageClass">{{ message }}</span>
          </div>
        </div>
      </div>

      <div class="modal-backdrop" v-if="pendingDelete" @click.self="cancelDelete">
        <div class="modal">
          <h3>Delete research?</h3>
          <p>This will permanently remove the research entry for <strong>{{ pendingDelete.ticker }}</strong>.</p>
          <div class="toolbar">
            <button class="btn-danger" @click="confirmDelete">Delete</button>
            <button class="btn-ghost" @click="cancelDelete">Cancel</button>
          </div>
        </div>
      </div>
    </div>
  `,
  setup() { return { fmtDate, decisionClass, assessmentClass, statusClass, fmtPct, fmtMoney }; },
};
