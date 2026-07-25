import { get, post, put, del, isoToday, fmtDate, decisionClass, assessmentClass, statusClass, fmtPct, fmtMoney, sortRows, toggleSortState } from "../utils.js";

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
      saving: false,
      saveError: null,
      pendingDelete: null,
      valuation: null,
      valuationPreview: false,
      prefillValuationInputs: null,  // stashed raw inputs; persisted when research is saved
      prefilling: false,
      prefillInfo: null,
      prefillError: null,
      listSort: { key: "updated_at", dir: "desc" },
      smSort: { key: "weight", dir: "desc" },
      picker: { open: false, ticker: "", match: null, checked: false },
    };
  },
  computed: {
    fundFields() { return FUND_FIELDS; },
    sortedList() { return sortRows(this.list, this.listSort.key, this.listSort.dir); },
    sortedHolders() {
      if (!this.smHolders) return [];
      return sortRows(this.smHolders.holders || [], this.smSort.key, this.smSort.dir);
    },
    sortedExited() {
      if (!this.smHolders) return [];
      return sortRows(this.smHolders.exited || [], this.smSort.key, this.smSort.dir);
    },
    fundamentalsScore() {
      return FUND_FIELDS.reduce((acc, [k]) => acc + (this.form[k] ? 1 : 0), 0);
    },
    isEdit() { return this.mode === "edit"; },
    isNew() { return this.mode === "new"; },
    criticalCriteria() {
      const can_trade = this.form.f_roe && this.form.f_npm && this.form.sm_holding_5pct;
      return {
        roe_strong: !!this.form.f_roe,
        npm_positive: !!this.form.f_npm,
        sm_present: !!this.form.sm_holding_5pct,
        price_below_mos: !!this.form.price_below_mos,
        can_trade,
        can_invest: can_trade && !!this.form.price_below_mos,
      };
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
    newForm(prefillTicker) {
      this.form = this._emptyForm();
      if (prefillTicker) this.form.ticker = String(prefillTicker).trim().toUpperCase();
      this.smHolders = null;
      this.valuation = null;
      this.saveError = null;
      this.mode = "new";
      if (this.form.ticker) {
        // Kick off background lookups so company / valuation / SM data populate.
        this.fetchSmartMoney();
        this.fetchValuation();
        this.prefillCompany(false);
      }
    },
    sortList(col) { toggleSortState(this.listSort, col); },
    sortHolders(col) { toggleSortState(this.smSort, col); },
    openPicker() {
      this.picker = { open: true, ticker: "", match: null, checked: false };
      this.$nextTick(() => {
        const el = document.getElementById("research-picker-input");
        if (el) el.focus();
      });
    },
    closePicker() { this.picker.open = false; },
    onPickerInput() {
      const t = (this.picker.ticker || "").trim().toUpperCase();
      this.picker.match = t ? (this.list.find(r => (r.ticker || "").toUpperCase() === t) || null) : null;
      this.picker.checked = !!t;
    },
    pickerSubmit() {
      const t = (this.picker.ticker || "").trim().toUpperCase();
      if (!t) return;
      this.onPickerInput();
      const match = this.picker.match;
      this.picker.open = false;
      if (match) this.editForm(match);
      else this.newForm(t);
    },
    openExistingFromPicker() {
      if (!this.picker.match) return;
      const match = this.picker.match;
      this.picker.open = false;
      this.editForm(match);
    },
    startNewFromPicker() {
      const t = (this.picker.ticker || "").trim().toUpperCase();
      this.picker.open = false;
      this.newForm(t);
    },
    editForm(row) {
      this.form = { ...this._emptyForm(), ...row };
      Object.keys(this.form).forEach(k => {
        if (typeof row[k] === "number" && (k.startsWith("f_") || k.endsWith("_ok") || k === "price_below_mos" || k === "sm_holding_5pct" || k === "sm_top3_increasing" || k === "market_cap_ok")) {
          this.form[k] = row[k] === 1;
        }
      });
      this.smHolders = null;
      this.valuation = null;
      this.saveError = null;
      this.mode = "edit";
      this.fetchSmartMoney();
      this.fetchValuation();
    },
    cancel() { this.mode = "list"; this.smHolders = null; this.saveError = null; },
    async onTickerBlur() {
      await Promise.all([this.fetchSmartMoney(), this.fetchValuation(), this.prefillCompany(false)]);
    },
    async prefillCompany(force) {
      const t = (this.form.ticker || "").trim().toUpperCase();
      if (!t) return;
      try {
        const data = await get(`/api/company/${t}${force ? "?refresh=1" : ""}`);
        if (!data) return;
        if (force || !this.form.company_name) this.form.company_name = data.company_name || this.form.company_name;
      } catch (e) { console.error(e); }
    },
    // Full SEC/EDGAR prefill: fills the objective checklist flags + company name.
    // Leaves technicals, notes and decision alone (those are your judgement).
    async prefillResearch() {
      const t = (this.form.ticker || "").trim().toUpperCase();
      if (!t) return;
      this.prefilling = true;
      this.prefillError = null;
      this.prefillInfo = null;
      try {
        const d = await get(`/api/prefill/${t}`);
        if (d.company_name) this.form.company_name = d.company_name;
        const flagKeys = [
          "f_roa", "f_roe", "f_roi", "f_npm", "f_eps_5yr", "f_eps_1yr", "f_eps_next",
          "f_sales_5yr", "f_current_ratio", "f_debt_equity",
          "market_cap_ok", "sm_holding_5pct", "price_below_mos",
        ];
        for (const k of flagKeys) {
          if (d.flags && k in d.flags) this.form[k] = !!d.flags[k];
        }
        this.prefillInfo = d;
        await this.previewFromPrefill(d);
      } catch (e) {
        this.prefillError = e.message;
      } finally {
        this.prefilling = false;
      }
    },
    // Compute a live valuation from the prefill inputs so the Valuation Summary
    // shows the numbers Prefill used. The preview is stashed and persisted only
    // when you save the research (see _persistPrefilledValuation). Skipped for
    // financials / vetoed names.
    async previewFromPrefill(d) {
      const v = d && d.valuation;
      if (!v || d.financial || d.veto) return;
      const p = {
        current_price: v.current_price,
        required_return: v.required_return,
        total_equity_m: v.total_equity_m,
        shares_outstanding_m: v.shares_outstanding_m,
      };
      let hasRoe = false;
      for (let i = 1; i <= 5; i++) {
        p[`roe${i}`] = v[`roe${i}`];
        // prefill emits payout as % (e.g. 27); the API expects a decimal (0.27)
        p[`payout${i}`] = v[`payout${i}`] != null ? v[`payout${i}`] / 100 : null;
        if (v[`roe${i}`] != null) hasRoe = true;
      }
      if (!hasRoe || !(Number(p.shares_outstanding_m) > 0)) return;
      try {
        const result = await post("/api/valuation/preview", p);
        this.valuation = { ...result, current_price: v.current_price };
        this.valuationPreview = true;
        this.prefillValuationInputs = { ...p, company_name: d.company_name || this.form.company_name };
      } catch (e) { console.error(e); }
    },
    // Discard the prefilled (unsaved) valuation preview and restore any saved one.
    resetPrefilledValuation() {
      this.prefillValuationInputs = null;
      this.valuationPreview = false;
      this.fetchValuation();
    },
    // Persist a prefilled valuation preview when the research is saved, linking it
    // to the research record. No-op if nothing was prefilled or it's already saved.
    async _persistPrefilledValuation() {
      if (!this.prefillValuationInputs) return;
      const t = (this.form.ticker || "").trim().toUpperCase();
      if (!t) return;
      try {
        const body = {
          ...this.prefillValuationInputs,
          ticker: t,
          valuation_date: isoToday(),
        };
        if (this.form.id) body.research_id = this.form.id;
        const saved = await post("/api/valuation", body);
        this.valuation = saved || this.valuation;
        this.valuationPreview = false;
        this.prefillValuationInputs = null;
      } catch (e) { console.error(e); }
    },
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
    async fetchValuation() {
      const t = (this.form.ticker || "").trim().toUpperCase();
      if (!t) { this.valuation = null; return; }
      try {
        const data = await get(`/api/valuation/${t}`);
        this.valuation = data || null;
        this.valuationPreview = false;
      } catch (e) {
        console.error(e);
        this.valuation = null;
      }
    },
    payload() {
      const p = { ...this.form };
      Object.keys(p).forEach(k => {
        if (typeof p[k] === "boolean") p[k] = p[k] ? 1 : 0;
      });
      p.ticker = (p.ticker || "").toUpperCase();
      return p;
    },
    async _doSave() {
      if (!this.form.ticker) { this.saveError = "Ticker required"; return false; }
      this.saving = true;
      this.saveError = null;
      try {
        let data;
        if (this.mode === "edit" && this.form.id) {
          data = await put(`/api/research/${this.form.id}`, this.payload());
        } else {
          data = await post("/api/research", this.payload());
        }
        await this.loadList();
        // Update form id in case this was a new record, without full editForm reset
        this.form.id = data.id;
        this.mode = "edit";
        // Persist any prefilled valuation preview, now that we have a research id to link.
        await this._persistPrefilledValuation();
        return true;
      } catch (e) {
        this.saveError = e.message;
        return false;
      } finally {
        this.saving = false;
      }
    },
    async saveAndReturn() {
      const ok = await this._doSave();
      if (ok) { this.mode = "list"; this.smHolders = null; }
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
        this.saveError = e.message;
        this.pendingDelete = null;
      }
    },
    async openValuation() {
      if (!this.form.ticker) { alert("Enter a ticker first."); return; }
      const ok = await this._doSave();
      if (!ok) return;
      const rid = this.form.id;
      const t = this.form.ticker.toUpperCase();
      this.$router.push(rid ? `/valuation/${t}?from_research=${rid}` : `/valuation/${t}`);
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
          <button class="btn-primary" @click="openPicker">+ New Research</button>
        </div>
        <div class="card" v-if="list.length">
          <div class="table-wrap"><table class="table">
            <thead>
              <tr>
                <sort-th col="ticker" :sort="listSort" @sort="sortList">Ticker</sort-th>
                <sort-th col="date_researched" :sort="listSort" @sort="sortList">Date</sort-th>
                <sort-th col="fundamentals_score" :sort="listSort" @sort="sortList">Score</sort-th>
                <sort-th col="decision" :sort="listSort" @sort="sortList">Decision</sort-th>
                <sort-th col="valuation_assessment" :sort="listSort" @sort="sortList">Valuation</sort-th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in sortedList" :key="r.id" class="clickable" @click="editForm(r)">
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
          </table></div>
        </div>
        <div class="empty" v-else>No research yet. Click "New Research" to start.</div>
      </div>

      <div v-else>
        <div class="toolbar">
          <h1 style="margin: 0;">{{ isEdit ? form.ticker + ' — Edit' : 'New Research' }}</h1>
          <div class="spacer"></div>
          <span v-if="saveError" class="text-red" style="font-size: 0.85rem; margin-right: 0.5rem;">{{ saveError }}</span>
          <button class="btn-primary" :disabled="saving || !form.ticker" @click="saveAndReturn">
            {{ saving ? 'Saving…' : 'Save & Return' }}
          </button>
          <button @click="cancel" style="margin-left: 0.5rem;">Cancel</button>
        </div>

        <div class="card" v-if="prefillError" style="border-left: 4px solid var(--red); padding: 0.6rem 0.9rem;">
          <span class="text-red">Prefill: {{ prefillError }}</span>
        </div>
        <div class="card" v-if="prefillInfo" style="border-left: 4px solid var(--accent); padding: 0.6rem 0.9rem;">
          <div style="display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap; font-size: 0.85rem;">
            <strong>Prefilled from SEC EDGAR</strong>
            <span class="text-muted">Price {{ fmtMoney(prefillInfo.price) }} <span v-if="prefillInfo.price_src">[{{ prefillInfo.price_src }}]</span></span>
            <span v-if="prefillInfo.verdict" :class="prefillInfo.verdict.startsWith('CAN') ? 'text-green' : (prefillInfo.verdict.startsWith('VETO') ? 'text-red' : 'text-muted')" style="font-weight: 600;">▶ {{ prefillInfo.verdict }}</span>
          </div>
          <div v-if="prefillInfo.financial" class="text-red" style="font-size: 0.8rem; margin-top: 0.35rem;">
            ⚠ Financial sector ({{ prefillInfo.sic_desc }}) — equity-multiple valuation does not apply; skip until a bank method is defined.
          </div>
          <div v-else-if="prefillInfo.veto" class="text-red" style="font-size: 0.8rem; margin-top: 0.35rem;">
            ⚠ Valuation vetoed — {{ prefillInfo.veto_reason }}.
          </div>
          <div class="text-muted" style="font-size: 0.78rem; margin-top: 0.35rem;">
            Fundamentals + Price&lt;MOS auto-filled. Still check manually: <strong>Technicals</strong> (TradingView), <strong>Top 3 SM Increasing</strong>, liquidity. EPS-next is an estimate.
          </div>
        </div>

        <div class="grid-2">
          <div class="card">
            <h3>Stock</h3>
            <div class="grid-2">
              <div class="field">
                <label>Ticker</label>
                <input type="text" v-model="form.ticker" @blur="onTickerBlur" placeholder="AAPL">
              </div>
              <div class="field">
                <label>Company <button type="button" class="btn-ghost" style="font-size: 0.75rem; padding: 0 0.4rem; margin-left: 0.4rem;" :disabled="!form.ticker || prefilling" @click="prefillResearch()" title="Auto-fill fundamentals from SEC EDGAR">{{ prefilling ? 'Prefilling…' : 'Prefill' }}</button></label>
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
                <span>SM Holding &gt; 2% (preferably &gt;5%)</span>
              </label>
              <label class="check-item" :class="{ checked: form.sm_top3_increasing }">
                <input type="checkbox" v-model="form.sm_top3_increasing">
                <span>Top 3 SM Increasing Stake</span>
              </label>
              <label class="check-item" :class="{ checked: form.price_below_mos }">
                <input type="checkbox" v-model="form.price_below_mos">
                <span>Price &lt; Margin of Safety</span>
              </label>
            </div>
          </div>

          <div class="card">
            <h3>Technicals</h3>
            <p class="text-muted" style="font-size: 0.8rem; margin: 0 0 0.6rem;">Check in TradingView before entering:</p>
            <div style="background: var(--bg-3); border-radius: 4px; padding: 0.75rem; font-size: 0.85rem; line-height: 2;">
              <div><strong>RSI</strong> — Trade: &lt; 35 &amp; trending up &nbsp;|&nbsp; Invest: &lt; 40 &amp; trending up</div>
              <div><strong>STO Slow</strong> — &lt; 20</div>
              <div><strong>STO Cross</strong> — Fast over Slow</div>
              <div><strong>Liquidity</strong> — Avg Daily Vol &gt; 10× your position size</div>
            </div>
          </div>
        </div>

        <div class="card" style="border: 2px solid var(--accent);">
          <h3 style="margin-top: 0; color: var(--accent);">Critical Criteria</h3>
          <p class="text-muted" style="font-size: 0.85rem; margin: 0 0 0.75rem;">
            <span class="badge blue">TRADE</span> requires first 3 &nbsp;|&nbsp;
            <span class="badge green">INVEST</span> requires all 4
          </p>
          <div style="display: grid; gap: 0.5rem; margin-bottom: 1rem;">
            <div style="display: flex; align-items: center; padding: 0.65rem 0.75rem; border-radius: 4px; background: var(--bg-3);"
                 :style="{ borderLeft: '4px solid ' + (criticalCriteria.roe_strong ? 'var(--green)' : 'var(--red)') }">
              <span class="badge blue" style="font-size: 0.7em; margin-right: 0.6rem; flex-shrink: 0;">TRADE</span>
              <span style="flex: 1;">ROE &gt; 12%</span>
              <span style="font-weight: 600;" :class="criticalCriteria.roe_strong ? 'text-green' : 'text-red'">{{ criticalCriteria.roe_strong ? 'PASS' : 'FAIL' }}</span>
            </div>
            <div style="display: flex; align-items: center; padding: 0.65rem 0.75rem; border-radius: 4px; background: var(--bg-3);"
                 :style="{ borderLeft: '4px solid ' + (criticalCriteria.npm_positive ? 'var(--green)' : 'var(--red)') }">
              <span class="badge blue" style="font-size: 0.7em; margin-right: 0.6rem; flex-shrink: 0;">TRADE</span>
              <span style="flex: 1;">Net Profit Margin &gt; 0%</span>
              <span style="font-weight: 600;" :class="criticalCriteria.npm_positive ? 'text-green' : 'text-red'">{{ criticalCriteria.npm_positive ? 'PASS' : 'FAIL' }}</span>
            </div>
            <div style="display: flex; align-items: center; padding: 0.65rem 0.75rem; border-radius: 4px; background: var(--bg-3);"
                 :style="{ borderLeft: '4px solid ' + (criticalCriteria.sm_present ? 'var(--green)' : 'var(--red)') }">
              <span class="badge blue" style="font-size: 0.7em; margin-right: 0.6rem; flex-shrink: 0;">TRADE</span>
              <span style="flex: 1;">SM Holding &gt; 2%</span>
              <span style="font-weight: 600;" :class="criticalCriteria.sm_present ? 'text-green' : 'text-red'">{{ criticalCriteria.sm_present ? 'PASS' : 'FAIL' }}</span>
            </div>
            <div style="display: flex; align-items: center; padding: 0.65rem 0.75rem; border-radius: 4px; background: var(--bg-3);"
                 :style="{ borderLeft: '4px solid ' + (criticalCriteria.price_below_mos ? 'var(--green)' : 'var(--red)') }">
              <span class="badge green" style="font-size: 0.7em; margin-right: 0.6rem; flex-shrink: 0;">INVEST</span>
              <span style="flex: 1;">Price &lt; Margin of Safety</span>
              <span style="font-weight: 600;" :class="criticalCriteria.price_below_mos ? 'text-green' : 'text-red'">{{ criticalCriteria.price_below_mos ? 'PASS' : 'FAIL' }}</span>
            </div>
          </div>
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem;">
            <div style="padding: 0.65rem; border-radius: 4px; text-align: center; font-weight: 700; font-size: 1.05em;"
                 :style="{ background: criticalCriteria.can_trade ? 'rgba(0,200,100,0.12)' : 'rgba(200,50,50,0.12)', border: '1px solid ' + (criticalCriteria.can_trade ? 'var(--green)' : 'var(--red)') }"
                 :class="criticalCriteria.can_trade ? 'text-green' : 'text-red'">
              {{ criticalCriteria.can_trade ? 'CAN TRADE' : 'NOT READY TO TRADE' }}
            </div>
            <div style="padding: 0.65rem; border-radius: 4px; text-align: center; font-weight: 700; font-size: 1.05em;"
                 :style="{ background: criticalCriteria.can_invest ? 'rgba(0,200,100,0.12)' : 'rgba(200,50,50,0.12)', border: '1px solid ' + (criticalCriteria.can_invest ? 'var(--green)' : 'var(--red)') }"
                 :class="criticalCriteria.can_invest ? 'text-green' : 'text-red'">
              {{ criticalCriteria.can_invest ? 'CAN INVEST' : 'NOT READY TO INVEST' }}
            </div>
          </div>
        </div>

        <div class="card">
          <h3>Valuation Summary</h3>
          <div v-if="valuation" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 1rem; margin-bottom: 1rem;">
            <div style="padding: 0.75rem; border-radius: 4px; background: var(--bg-3); text-align: center;">
              <div class="text-muted" style="font-size: 0.8rem; margin-bottom: 0.25rem;">Current Price</div>
              <div style="font-weight: 600; font-size: 1.1em;">{{ fmtMoney(valuation.current_price) }}</div>
            </div>
            <div style="padding: 0.75rem; border-radius: 4px; background: var(--bg-3); text-align: center;">
              <div class="text-muted" style="font-size: 0.8rem; margin-bottom: 0.25rem;">MOS Valuation</div>
              <div style="font-weight: 600; font-size: 1.1em;">{{ fmtMoney(valuation.valuation_mos) }}</div>
            </div>
            <div style="padding: 0.75rem; border-radius: 4px; background: var(--bg-3); text-align: center;">
              <div class="text-muted" style="font-size: 0.8rem; margin-bottom: 0.25rem;">Discount %</div>
              <div style="font-weight: 600; font-size: 1.1em;" :class="valuation.discount_mos_pct >= 0 ? 'text-green' : 'text-red'">{{ (valuation.discount_mos_pct).toFixed(1) }}%</div>
            </div>
            <div style="padding: 0.75rem; border-radius: 4px; background: var(--bg-3); text-align: center;">
              <div class="text-muted" style="font-size: 0.8rem; margin-bottom: 0.25rem;">Assessment</div>
              <div style="font-weight: 600;"><span :class="assessmentClass(valuation.assessment)">{{ valuation.assessment }}</span></div>
            </div>
          </div>
          <div class="toolbar">
            <button @click="openValuation" :disabled="!form.ticker || saving">{{ saving ? 'Saving...' : 'Edit Valuation →' }}</button>
            <button v-if="valuationPreview" class="btn-ghost" @click="resetPrefilledValuation" :disabled="saving" title="Discard the prefilled valuation">Reset</button>
            <span class="text-muted" v-if="!valuation">No valuation saved yet — clicking Edit Valuation will save your research first.</span>
            <span class="text-muted" v-else-if="valuationPreview">From Prefill — saves automatically when you save this research (or use Edit Valuation).</span>
            <span class="text-muted" v-else>Last saved: {{ valuation.valuation_date }}</span>
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
            <div class="table-wrap"><table class="table">
              <thead>
                <tr>
                  <sort-th col="name" :sort="smSort" @sort="sortHolders">Guru</sort-th>
                  <sort-th col="firm" :sort="smSort" @sort="sortHolders">Firm</sort-th>
                  <sort-th col="weight" :sort="smSort" @sort="sortHolders" :num="true">Weight</sort-th>
                  <sort-th col="weight_change" :sort="smSort" @sort="sortHolders" :num="true">Δ Weight</sort-th>
                  <sort-th col="status" :sort="smSort" @sort="sortHolders">Status</sort-th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="h in sortedHolders" :key="h.name">
                  <td>{{ h.name }}</td>
                  <td class="text-muted">{{ h.firm }}</td>
                  <td class="num">{{ h.weight ? h.weight.toFixed(2) + '%' : '—' }}</td>
                  <td class="num" :class="statusClass(h.status)">
                    {{ h.weight_change != null ? (h.weight_change > 0 ? '+' : '') + h.weight_change.toFixed(2) + 'pp' : '—' }}
                  </td>
                  <td><span :class="statusClass(h.status)">{{ h.status }}</span></td>
                </tr>
                <tr v-for="e in sortedExited" :key="'x'+e.name">
                  <td>{{ e.name }}</td>
                  <td class="text-muted">{{ e.firm }}</td>
                  <td class="num text-muted">0.00%</td>
                  <td class="num text-red">{{ e.weight_change != null ? e.weight_change.toFixed(2) + 'pp' : '—' }}</td>
                  <td><span class="text-red">Exited</span></td>
                </tr>
              </tbody>
            </table></div>
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
        </div>
      </div>

      <div class="modal-backdrop" v-if="picker.open" @click.self="closePicker">
        <div class="modal">
          <h3>New Research</h3>
          <p class="text-muted" style="margin-top: 0;">Enter a ticker. If you've researched it before, you can open and amend the existing entry — otherwise start a new one.</p>
          <div class="field">
            <label>Ticker</label>
            <input id="research-picker-input" type="text" v-model="picker.ticker"
                   @input="onPickerInput"
                   @keyup.enter="pickerSubmit"
                   placeholder="AAPL" autocomplete="off">
          </div>
          <div v-if="picker.checked && picker.match" style="margin: 0.75rem 0; padding: 0.75rem; border-radius: 4px; background: var(--bg-3);">
            <strong>{{ picker.match.ticker }}</strong>
            <span class="text-muted"> — {{ picker.match.company_name || 'no name' }}</span>
            <div class="text-muted" style="font-size: 0.8rem; margin-top: 0.25rem;">
              Last researched {{ fmtDate(picker.match.date_researched) }} · Score {{ picker.match.fundamentals_score }}/10 ·
              <span :class="decisionClass(picker.match.decision)">{{ picker.match.decision || 'NO_ACTION' }}</span>
            </div>
          </div>
          <div v-else-if="picker.checked && picker.ticker" class="text-muted" style="margin: 0.75rem 0; font-size: 0.85rem;">
            No prior research for <strong>{{ picker.ticker.toUpperCase() }}</strong>. A new entry will be started.
          </div>
          <div class="modal-actions">
            <button class="btn-ghost" @click="closePicker">Cancel</button>
            <button v-if="picker.match" class="btn-primary" @click="openExistingFromPicker">Open &amp; Amend</button>
            <button v-if="picker.match" @click="startNewFromPicker">Start New Anyway</button>
            <button v-else class="btn-primary" :disabled="!picker.ticker" @click="startNewFromPicker">Start New</button>
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
