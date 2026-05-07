import { post, get, fmtMoney, fmtNum, fmtPct, isoToday, assessmentClass } from "../utils.js";

const ROE_KEYS = ["roe1", "roe2", "roe3", "roe4", "roe5"];
const PAYOUT_KEYS = ["payout1", "payout2", "payout3", "payout4", "payout5"];
const NUMERIC_KEYS = [
  "current_price",
  ...ROE_KEYS, ...PAYOUT_KEYS,
  "required_return", "total_equity_m", "shares_outstanding_m",
];

export const Valuation = {
  props: ["ticker"],
  data() {
    return {
      form: this._initForm(),
      result: null,
      saving: false,
      message: null,
      messageClass: "",
    };
  },
  computed: {
    canCompute() {
      const f = this.form;
      const hasRoe = ROE_KEYS.some(k => f[k] !== null && f[k] !== "");
      return hasRoe && Number(f.shares_outstanding_m) > 0 && Number(f.total_equity_m) >= 0;
    },
    canSave() { return this.canCompute && !!this.form.ticker; },
  },
  watch: {
    form: { deep: true, handler() { this.recompute(); } },
  },
  methods: {
    _initForm() {
      const f = {
        ticker: "", company_name: "",
        valuation_date: isoToday(),
        current_price: null,
        required_return: 10,
        total_equity_m: null,
        shares_outstanding_m: null,
      };
      for (const k of ROE_KEYS) f[k] = null;
      for (const k of PAYOUT_KEYS) f[k] = null;
      return f;
    },
    payload() {
      const p = { ...this.form };
      NUMERIC_KEYS.forEach(k => {
        if (p[k] === "" || p[k] == null) p[k] = null;
        else p[k] = Number(p[k]);
      });
      // Convert payout from % input (e.g. 27) to decimal (0.27) for the API
      for (const k of PAYOUT_KEYS) {
        if (p[k] != null) p[k] = p[k] / 100;
      }
      p.ticker = (p.ticker || "").toUpperCase();
      return p;
    },
    async recompute() {
      if (!this.canCompute) { this.result = null; return; }
      try {
        this.result = await post("/api/valuation/preview", this.payload());
      } catch (e) {
        this.result = null;
      }
    },
    async save() {
      if (!this.canSave) return;
      this.saving = true;
      this.message = null;
      try {
        const data = await post("/api/valuation", this.payload());
        this.result = data;
        this.message = "Saved";
        this.messageClass = "text-green";
      } catch (e) {
        this.message = `Error: ${e.message}`;
        this.messageClass = "text-red";
      } finally {
        this.saving = false;
        setTimeout(() => { this.message = null; }, 3000);
      }
    },
    async loadLatest() {
      if (!this.form.ticker) return;
      try {
        const data = await get(`/api/valuation/${this.form.ticker.toUpperCase()}`);
        if (!data) return;
        const next = this._initForm();
        next.ticker = data.ticker;
        next.company_name = data.company_name || "";
        next.valuation_date = data.valuation_date || isoToday();
        next.current_price = data.current_price;
        next.required_return = data.required_return ?? 10;
        next.total_equity_m = data.total_equity_m;
        next.shares_outstanding_m = data.shares_outstanding_m;
        for (const k of ROE_KEYS) next[k] = data[k] ?? null;
        // DB stores payout as decimal; convert to % for display
        for (const k of PAYOUT_KEYS) next[k] = data[k] != null ? data[k] * 100 : null;
        this.form = next;
      } catch (e) { console.error(e); }
    },
    fmtRoe(v) { return v == null ? "—" : `${Number(v).toFixed(2)}%`; },
  },
  mounted() {
    if (this.ticker) {
      this.form.ticker = this.ticker.toUpperCase();
      this.loadLatest();
    }
  },
  template: `
    <div>
      <h1>Equity Multiple Valuation</h1>

      <div class="grid-2">
        <div class="card">
          <h3>Inputs</h3>
          <div class="grid-2">
            <div class="field">
              <label>Stock Code</label>
              <input type="text" v-model="form.ticker" @blur="loadLatest()" placeholder="ADBE">
            </div>
            <div class="field">
              <label>Company</label>
              <input type="text" v-model="form.company_name" placeholder="Adobe Inc.">
            </div>
            <div class="field">
              <label>Date</label>
              <input type="date" v-model="form.valuation_date">
            </div>
            <div class="field">
              <label>Current Stock Price</label>
              <input type="number" step="0.01" v-model.number="form.current_price">
            </div>
          </div>

          <h3 style="margin-top: 1rem;">Return on Equity (5 years)</h3>
          <div class="grid-5">
            <div class="field">
              <label>Year 1 (latest)</label>
              <input type="number" step="0.01" v-model.number="form.roe1" placeholder="%">
            </div>
            <div class="field">
              <label>Year 2</label>
              <input type="number" step="0.01" v-model.number="form.roe2" placeholder="%">
            </div>
            <div class="field">
              <label>Year 3</label>
              <input type="number" step="0.01" v-model.number="form.roe3" placeholder="%">
            </div>
            <div class="field">
              <label>Year 4</label>
              <input type="number" step="0.01" v-model.number="form.roe4" placeholder="%">
            </div>
            <div class="field">
              <label>Year 5</label>
              <input type="number" step="0.01" v-model.number="form.roe5" placeholder="%">
            </div>
          </div>

          <h3 style="margin-top: 1rem;">Dividend Payout Ratio (5 years)</h3>
          <p class="text-muted" style="margin: -0.25rem 0 0.5rem;">As percentages: 0 = no dividend, 30 = 30% paid out.</p>
          <div class="grid-5">
            <div class="field">
              <label>Year 1</label>
              <input type="number" step="0.1" v-model.number="form.payout1" placeholder="%">
            </div>
            <div class="field">
              <label>Year 2</label>
              <input type="number" step="0.1" v-model.number="form.payout2" placeholder="%">
            </div>
            <div class="field">
              <label>Year 3</label>
              <input type="number" step="0.1" v-model.number="form.payout3" placeholder="%">
            </div>
            <div class="field">
              <label>Year 4</label>
              <input type="number" step="0.1" v-model.number="form.payout4" placeholder="%">
            </div>
            <div class="field">
              <label>Year 5</label>
              <input type="number" step="0.1" v-model.number="form.payout5" placeholder="%">
            </div>
          </div>

          <h3 style="margin-top: 1rem;">Equity</h3>
          <div class="grid-3">
            <div class="field">
              <label>Required Return %</label>
              <input type="number" step="0.01" v-model.number="form.required_return">
            </div>
            <div class="field">
              <label>Total Equity ($ M)</label>
              <input type="number" step="0.01" v-model.number="form.total_equity_m">
            </div>
            <div class="field">
              <label>Shares Outstanding (M)</label>
              <input type="number" step="0.01" v-model.number="form.shares_outstanding_m">
            </div>
          </div>

          <div class="toolbar">
            <button class="btn-primary" :disabled="!canSave || saving" @click="save">
              {{ saving ? "Saving..." : "Save Valuation" }}
            </button>
            <span :class="messageClass">{{ message }}</span>
          </div>
        </div>

        <div class="card">
          <h3>Results</h3>
          <div v-if="!result" class="empty">Enter at least one ROE year, total equity, and shares to compute.</div>
          <div v-else>
            <div class="grid-3">
              <div class="val-cell">
                <div class="label">Equity Per Share</div>
                <div class="num">{{ fmtMoney(result.equity_per_share) }}</div>
              </div>
              <div class="val-cell">
                <div class="label">Current Price</div>
                <div class="num">{{ fmtMoney(form.current_price) }}</div>
              </div>
              <div class="val-cell">
                <div class="label">Assessment</div>
                <div><span :class="assessmentClass(result.assessment)">{{ result.assessment }}</span></div>
              </div>
            </div>

            <div class="table-wrap" style="margin-top: 1rem;"><table class="table">
              <thead>
                <tr><th></th><th class="num">Average</th><th class="num">Median</th><th class="num">MOS (10% disc)</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Normalised ROE</td>
                  <td class="num">{{ fmtRoe(result.roe_avg) }}</td>
                  <td class="num">{{ fmtRoe(result.roe_median) }}</td>
                  <td class="num">{{ fmtRoe(result.roe_mos) }}</td>
                </tr>
                <tr>
                  <td>Distributed</td>
                  <td class="num">{{ fmtRoe(result.distributed_avg) }}</td>
                  <td class="num">{{ fmtRoe(result.distributed_median) }}</td>
                  <td class="num">{{ fmtRoe(result.distributed_mos) }}</td>
                </tr>
                <tr>
                  <td>Reinvested</td>
                  <td class="num">{{ fmtRoe(result.reinvested_avg) }}</td>
                  <td class="num">{{ fmtRoe(result.reinvested_median) }}</td>
                  <td class="num">{{ fmtRoe(result.reinvested_mos) }}</td>
                </tr>
                <tr>
                  <td>Equity Multiplier</td>
                  <td class="num">{{ fmtNum(result.multiplier_avg) }}</td>
                  <td class="num">{{ fmtNum(result.multiplier_median) }}</td>
                  <td class="num">{{ fmtNum(result.multiplier_mos) }}</td>
                </tr>
                <tr>
                  <td>Valuation</td>
                  <td class="num">{{ fmtMoney(result.valuation_avg) }}</td>
                  <td class="num">{{ fmtMoney(result.valuation_median) }}</td>
                  <td class="num">{{ fmtMoney(result.valuation_mos) }}</td>
                </tr>
                <tr>
                  <td>Discount / Overvalued %</td>
                  <td class="num" :class="result.discount_avg_pct >= 0 ? 'text-green' : 'text-red'">
                    {{ fmtPct(result.discount_avg_pct) }}
                  </td>
                  <td class="num" :class="result.discount_median_pct >= 0 ? 'text-green' : 'text-red'">
                    {{ fmtPct(result.discount_median_pct) }}
                  </td>
                  <td class="num" :class="result.discount_mos_pct >= 0 ? 'text-green' : 'text-red'">
                    {{ fmtPct(result.discount_mos_pct) }}
                  </td>
                </tr>
              </tbody>
            </table></div>
          </div>
        </div>
      </div>
    </div>
  `,
  setup() { return { fmtMoney, fmtNum, fmtPct, assessmentClass }; },
};
