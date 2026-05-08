import { get, put, post } from "../utils.js";

const INDICATORS = [
  { key: "rsi",        label: "RSI",                hint: "≤ low = LOW position size · &lt; mid = MED · ≥ mid = HIGH" },
  { key: "stochastic", label: "Stochastic",          hint: "≤ low = LOW · &lt; mid = MED · ≥ mid = HIGH" },
  { key: "s5fi",       label: "S&P 500 % Above 50DMA (S5FI)", hint: "≤ low = LOW · &lt; mid = MED · ≥ mid = HIGH" },
  { key: "fear_greed", label: "Fear &amp; Greed",      hint: "≤ low = LOW · &lt; mid = MED · ≥ mid = HIGH" },
];

export const Settings = {
  data() {
    return {
      thresholds: null,
      saving: false,
      message: null,
      messageClass: "",
    };
  },
  async mounted() {
    await this.load();
  },
  methods: {
    async load() {
      try {
        this.thresholds = await get("/api/settings/pullback-thresholds");
      } catch (e) {
        this.message = `Error loading: ${e.message}`;
        this.messageClass = "text-red";
        this.thresholds = null;
      }
    },
    async save() {
      this.saving = true;
      this.message = null;
      try {
        const payload = {};
        for (const { key } of INDICATORS) {
          const t = this.thresholds[key];
          payload[key] = { low: Number(t.low), mid: Number(t.mid) };
        }
        this.thresholds = await put("/api/settings/pullback-thresholds", payload);
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
    async resetDefaults() {
      if (!confirm("Reset all pullback thresholds to defaults?")) return;
      try {
        this.thresholds = await post("/api/settings/pullback-thresholds/reset");
        this.message = "Reset to defaults";
        this.messageClass = "text-green";
        setTimeout(() => { this.message = null; }, 3000);
      } catch (e) {
        this.message = `Error: ${e.message}`;
        this.messageClass = "text-red";
      }
    },
  },
  computed: {
    indicators() { return INDICATORS; },
  },
  template: `
    <div>
      <h1>Settings</h1>

      <div class="card" v-if="thresholds">
        <h3>Pullback / Correction Thresholds</h3>
        <p class="text-muted">
          Each indicator scores 1 (LOW), 2 (MED), or 3 (HIGH). The worst score
          across the four sets the position size — LOW = 2%, MED = 1.5%, HIGH = 1%.
        </p>
        <div class="table-wrap"><table class="table">
          <thead>
            <tr>
              <th>Indicator</th>
              <th>Low (≤)</th>
              <th>Mid (&lt;)</th>
              <th>Hint</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="ind in indicators" :key="ind.key">
              <td>{{ ind.label }}</td>
              <td>
                <input type="number" step="0.1" v-model.number="thresholds[ind.key].low" style="width: 80px;">
              </td>
              <td>
                <input type="number" step="0.1" v-model.number="thresholds[ind.key].mid" style="width: 80px;">
              </td>
              <td class="text-muted" v-html="ind.hint"></td>
            </tr>
          </tbody>
        </table></div>
        <div class="toolbar">
          <button class="btn-primary" :disabled="saving" @click="save">
            {{ saving ? "Saving..." : "Save Thresholds" }}
          </button>
          <button class="btn-ghost" @click="resetDefaults">Reset to Defaults</button>
          <span :class="messageClass">{{ message }}</span>
        </div>
      </div>

      <div class="card">
        <h3>Crash / Recession (fixed)</h3>
        <p class="text-muted" style="margin: 0;">
          St. Louis Fed and VIX use the worst color across both indicators:
          any red → NO TRADE; any orange (no red) → CAUTION; otherwise OK.
          These thresholds are not adjustable.
        </p>
      </div>
    </div>
  `,
};
