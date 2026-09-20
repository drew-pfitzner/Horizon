// Statement-file import for the trade log.
//
// The panel never computes anything itself: it reads the chosen file, posts it
// to /preview, shows the plan the server built, and posts the same text back to
// /apply with the answers attached. Changing an answer re-previews, so what's on
// screen is always a plan the server just produced rather than one patched up in
// the browser.
import { post, fmtDate, fmtMoney, fmtShares } from "../utils.js";

const FIELD_LABELS = {
  entry_date: "Entry date", entry_price: "Entry price", shares: "Shares",
  entry_fee: "Entry fee", exit_date: "Exit date", exit_price: "Exit price",
  exit_fee: "Exit fee",
};

export const TradeImport = {
  emits: ["imported"],
  data() {
    return {
      csv: "",
      fileName: "",
      dragging: false,
      updatePortfolio: true,   // the statement's NAV replaces the stored one
      plan: null,
      resolutions: {},   // action key -> { mode, entry_date, entry_price }
      accepted: {},      // action key -> bool
      strategies: {},    // action key -> TRADE | INVEST
      expanded: {},      // action key -> show the individual fills
      loading: false,
      applying: false,
      error: null,
      result: null,
    };
  },
  computed: {
    actionable() {
      if (!this.plan) return [];
      return this.plan.actions.filter(a => a.action === "create" || a.action === "update");
    },
    questions() {
      if (!this.plan) return [];
      return this.plan.actions.filter(a => a.action === "ambiguous");
    },
    settled() {
      if (!this.plan) return [];
      return this.plan.actions.filter(a => a.action === "skip");
    },
    acceptedKeys() {
      return this.actionable.filter(a => this.accepted[a.key] !== false).map(a => a.key);
    },
    ignoredSummary() {
      if (!this.plan) return "";
      const entries = Object.entries(this.plan.ignored || {});
      if (!entries.length) return "";
      return entries.map(([k, n]) => `${n} × ${k}`).join(", ");
    },
    periodLabel() {
      if (!this.plan) return "";
      const p = this.plan.period || {};
      if (!p.start) return "";
      return p.start === p.end ? fmtDate(p.start) : `${fmtDate(p.start)} → ${fmtDate(p.end)}`;
    },
  },
  methods: {
    fmtDate, fmtMoney, fmtShares,
    fieldLabel(f) { return FIELD_LABELS[f] || f; },

    fmtVal(field, v) {
      if (v === null || v === undefined || v === "") return "—";
      if (field.endsWith("_date")) return fmtDate(v);
      if (field === "shares") return fmtShares(v);
      if (field.endsWith("_fee")) return Number(v).toFixed(4);
      return Number(v).toFixed(4);
    },

    fmtAmount(v, currency) {
      if (v === null || v === undefined || v === "") return "—";
      const n = Number(v).toLocaleString("en-US",
        { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      return currency ? `${n} ${currency}` : n;
    },

    onFile(event) {
      this.read(event.target.files && event.target.files[0]);
    },

    // Dropping the file on the panel is the same path as picking it.
    onDrop(event) {
      this.dragging = false;
      this.read(event.dataTransfer && event.dataTransfer.files[0]);
    },

    read(file) {
      if (!file) return;
      this.fileName = file.name;
      const reader = new FileReader();
      reader.onload = () => { this.csv = String(reader.result || ""); this.preview(); };
      reader.readAsText(file);
    },

    async preview() {
      if (!this.csv.trim()) { this.error = "Choose a CSV file."; return; }
      this.loading = true;
      this.error = null;
      this.result = null;
      try {
        this.plan = await post("/api/trades/import/preview",
                               { csv: this.csv, resolutions: this.resolutions });
        for (const a of this.plan.actions) {
          if (!(a.key in this.accepted)) this.accepted[a.key] = true;
          if (!(a.key in this.strategies)) this.strategies[a.key] = "TRADE";
        }
      } catch (e) {
        this.plan = null;
        this.error = e.message;
      } finally {
        this.loading = false;
      }
    },

    // Picking an option re-plans on the server, so the preview below the
    // question updates to show exactly what the answer would do.
    choose(key, mode) {
      this.resolutions[key] = { ...(this.resolutions[key] || {}), mode };
      if (mode === "entry" && !this.entryReady(key)) return;   // wait for the figures
      this.preview();
    },
    entryReady(key) {
      const r = this.resolutions[key] || {};
      return !!(r.entry_date && Number(r.entry_price) > 0);
    },
    onEntryInput(key) {
      if (this.entryReady(key)) this.preview();
    },

    async applyPlan() {
      this.applying = true;
      this.error = null;
      try {
        // `accept` gates the writes only. A "leave it out" answer rides along in
        // `resolutions` and is recorded by the server regardless, so the same
        // sale stops asking on next month's statement.
        this.result = await post("/api/trades/import/apply", {
          csv: this.csv,
          resolutions: this.resolutions,
          accept: this.acceptedKeys,
          strategies: this.strategies,
          update_portfolio: !!(this.plan.portfolio && this.updatePortfolio),
        });
        this.$emit("imported", this.result);
        await this.preview();     // re-plan: everything applied should now read "already imported"
      } catch (e) {
        this.error = e.message;
      } finally {
        this.applying = false;
      }
    },

    reset() {
      Object.assign(this, {
        csv: "", fileName: "", plan: null, resolutions: {}, accepted: {},
        strategies: {}, expanded: {}, error: null, result: null,
        updatePortfolio: true,
      });
      // Clearing the input's value matters: without it, choosing the same file
      // again fires no change event and the panel looks dead.
      if (this.$refs.file) this.$refs.file.value = "";
    },

    badgeClass(action) {
      if (action === "create") return "badge green";
      if (action === "update") return "badge";
      if (action === "ambiguous") return "badge red";
      return "badge";
    },
    badgeText(action) {
      return { create: "NEW", update: "UPDATE", ambiguous: "NEEDS YOU", skip: "DONE" }[action] || action;
    },
  },

  template: `
    <div class="import-panel">
      <div class="card import-drop" :class="{ dragging }"
           @dragover.prevent="dragging = true" @dragleave.prevent="dragging = false"
           @drop.prevent="onDrop">
        <div class="toolbar">
          <label class="btn btn-primary import-file">
            {{ loading ? 'Reading…' : 'Choose a CSV file…' }}
            <input type="file" accept=".csv,text/csv" ref="file" @change="onFile" hidden>
          </label>
          <span v-if="fileName" class="import-filename">{{ fileName }}</span>
          <span v-else class="text-muted" style="font-size:.8rem;">or drop it here</span>
          <div class="spacer"></div>
          <button class="btn-ghost" v-if="plan || csv" @click="reset">Clear</button>
        </div>

        <div v-if="error" class="text-red" style="margin-top:.5rem;">{{ error }}</div>
      </div>

      <div v-if="result" class="card import-result">
        <strong class="text-green">
          Imported — {{ result.created }} new, {{ result.updated }} updated,
          {{ result.fills_added }} fill(s) recorded.
        </strong>
        <div class="text-muted" style="font-size:.82rem; margin-top:.25rem;" v-if="result.tickers.length">
          {{ result.tickers.join(', ') }}
        </div>
        <div class="text-muted" style="font-size:.82rem; margin-top:.25rem;" v-if="result.portfolio">
          Portfolio value set to
          {{ fmtAmount(result.portfolio.value, result.portfolio.currency) }}.
        </div>
      </div>

      <template v-if="plan">
        <div class="card import-summary">
          <div class="import-stat">
            <div class="stat-label">Statement period</div>
            <div class="stat-value">{{ periodLabel || '—' }}</div>
            <div class="stat-note text-muted">Nothing outside these dates is touched.</div>
          </div>
          <div class="import-stat">
            <div class="stat-label">Fills in file</div>
            <div class="stat-value">{{ plan.fills_in_file }}</div>
            <div class="stat-note text-muted">
              {{ plan.fills_new }} new · {{ plan.fills_known }} already logged
            </div>
          </div>
          <div class="import-stat" v-if="plan.portfolio">
            <div class="stat-label">Portfolio value</div>
            <div class="stat-value">
              {{ fmtAmount(plan.portfolio.value, plan.portfolio.currency) }}
            </div>
            <div class="stat-note text-muted">
              now {{ fmtAmount(plan.portfolio.stored.value, plan.portfolio.stored.currency) }}
              <label class="import-nav-opt">
                <input type="checkbox" v-model="updatePortfolio">
                Update on apply
              </label>
            </div>
          </div>
          <div class="import-stat" v-if="plan.account">
            <div class="stat-label">Account</div>
            <div class="stat-value">{{ plan.account }}</div>
          </div>
          <div class="import-stat" v-if="ignoredSummary">
            <div class="stat-label">Not trades</div>
            <div class="stat-value" style="font-size:.9rem;">{{ ignoredSummary }}</div>
            <div class="stat-note text-muted">Forex legs, dividends and adjustments are skipped.</div>
          </div>
        </div>

        <div class="card" v-if="questions.length">
          <h3 style="margin-top:0;">Needs your call</h3>
          <div v-for="q in questions" :key="q.key" class="import-question">
            <div class="import-question-head">
              <strong>{{ q.ticker }}</strong>
              <span :class="badgeClass(q.action)">{{ badgeText(q.action) }}</span>
            </div>
            <p class="import-reason">{{ q.reason }}</p>
            <div class="import-options">
              <label v-for="opt in q.options" :key="opt.mode" class="import-option"
                     :class="{ checked: (resolutions[q.key] || {}).mode === opt.mode }">
                <input type="radio" :name="'q-' + q.key" :value="opt.mode"
                       :checked="(resolutions[q.key] || {}).mode === opt.mode"
                       @change="choose(q.key, opt.mode)">
                <span>
                  <strong>{{ opt.label }}</strong>
                  <span v-if="opt.recommended" class="text-muted" style="font-size:.75rem;"> · suggested</span>
                  <div class="text-muted" style="font-size:.8rem;">{{ opt.detail }}</div>
                </span>
              </label>
            </div>
            <div class="grid-2" v-if="(resolutions[q.key] || {}).mode === 'entry'" style="margin-top:.6rem;">
              <div class="field">
                <label>Entry date</label>
                <input type="date" :value="(resolutions[q.key] || {}).entry_date"
                       @input="resolutions[q.key].entry_date = $event.target.value; onEntryInput(q.key)">
              </div>
              <div class="field">
                <label>Average entry price</label>
                <input type="number" step="0.0001" :value="(resolutions[q.key] || {}).entry_price"
                       @input="resolutions[q.key].entry_price = $event.target.value"
                       @change="onEntryInput(q.key)">
              </div>
            </div>
          </div>
        </div>

        <div class="card" v-if="actionable.length">
          <div class="toolbar" style="margin-bottom:.5rem;">
            <h3 style="margin:0;">{{ actionable.length }} change(s) ready</h3>
            <div class="spacer"></div>
            <button class="btn-primary" :disabled="applying || !acceptedKeys.length" @click="applyPlan">
              {{ applying ? 'Applying…' : 'Apply ' + acceptedKeys.length + ' change(s)' }}
            </button>
          </div>

          <div v-for="a in actionable" :key="a.key" class="import-action">
            <div class="import-action-head">
              <label class="import-accept">
                <input type="checkbox" :checked="accepted[a.key] !== false"
                       @change="accepted[a.key] = $event.target.checked">
                <strong>{{ a.ticker }}</strong>
              </label>
              <span :class="badgeClass(a.action)">{{ badgeText(a.action) }}</span>
              <select v-if="a.action === 'create'" v-model="strategies[a.key]" class="import-strategy">
                <option value="TRADE">Trade</option>
                <option value="INVEST">Invest</option>
              </select>
              <div class="spacer"></div>
              <button class="btn-ghost" style="font-size:.75rem;"
                      @click="expanded[a.key] = !expanded[a.key]">
                {{ expanded[a.key] ? 'Hide' : 'Show' }} {{ a.fills.length }} fill(s)
              </button>
            </div>

            <p class="import-reason">{{ a.reason }}</p>

            <div v-for="(t, i) in a.targets" :key="i" class="import-target">
              <div class="import-target-label">
                <span class="badge">{{ t.slot === 'open' ? 'Open position' : 'Closed trade' }}</span>
                <span class="text-muted" style="font-size:.78rem;">
                  {{ fmtShares(t.derived.shares) }} sh @ {{ fmtMoney(t.derived.entry_price) }}
                  <template v-if="t.derived.exit_price">
                    → {{ fmtMoney(t.derived.exit_price) }} on {{ fmtDate(t.derived.exit_date) }}
                  </template>
                </span>
              </div>
              <table class="table import-diff" v-if="Object.keys(t.diff).length">
                <tbody>
                  <tr v-for="(d, field) in t.diff" :key="field">
                    <td style="width:9rem;">{{ fieldLabel(field) }}</td>
                    <td class="num text-muted">{{ fmtVal(field, d.was) }}</td>
                    <td style="width:1.5rem; text-align:center;">→</td>
                    <td class="num"><strong>{{ fmtVal(field, d.now) }}</strong></td>
                  </tr>
                </tbody>
              </table>
            </div>

            <table class="table import-fills" v-if="expanded[a.key]">
              <thead>
                <tr><th>Date</th><th>Side</th><th class="num">Qty</th>
                    <th class="num">Price</th><th class="num">Commission</th><th></th></tr>
              </thead>
              <tbody>
                <tr v-for="(f, i) in a.fills" :key="i">
                  <td>{{ fmtDate(f.date) }}</td>
                  <td :class="f.side === 'BUY' ? 'text-green' : 'text-red'">{{ f.side }}</td>
                  <td class="num">{{ fmtShares(f.qty) }}</td>
                  <td class="num">{{ fmtMoney(f.price) }}</td>
                  <td class="num">{{ f.commission != null ? f.commission.toFixed(4) : 'auto' }}</td>
                  <td class="text-muted" style="font-size:.75rem;">
                    {{ f.source === 'manual' ? 'already logged' : (f.known ? 'already imported' : 'new') }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div class="card" v-else-if="!questions.length">
          <strong class="text-green">Nothing to do — the log already matches this statement.</strong>
          <div class="text-muted" style="font-size:.84rem; margin-top:.3rem;">
            All {{ plan.fills_in_file }} fill(s) in this file are already recorded.
          </div>
          <!-- The trades may be old news while the NAV isn't. -->
          <div class="toolbar" style="margin-top:.6rem;" v-if="plan.portfolio && updatePortfolio">
            <button class="btn-ghost" :disabled="applying" @click="applyPlan">
              {{ applying ? 'Saving…' : 'Update portfolio value' }}
            </button>
          </div>
        </div>

        <div class="card" v-if="plan.notices.length">
          <h3 style="margin-top:0; font-size:.95rem;">Worth knowing</h3>
          <ul class="import-notices">
            <li v-for="(n, i) in plan.notices" :key="i">{{ n }}</li>
          </ul>
        </div>

        <div class="card" v-if="settled.length">
          <div class="text-muted" style="font-size:.82rem;">
            Already up to date: {{ settled.map(a => a.ticker).join(', ') }}
          </div>
        </div>
      </template>
    </div>
  `,
};
