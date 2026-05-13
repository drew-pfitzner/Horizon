import { get, post, fmtMoney, fmtNum, statusClass } from "../utils.js";

export const SmartMoney = {
  data() {
    return {
      tab: "ticker",
      tickerQuery: "",
      tickerResult: null,
      tickerLoading: false,
      guruQuery: "",
      guruResult: null,
      guruLoading: false,
      gurus: [],
      top: null,
      topLoading: false,
      update: { status: "idle", output: [], started_at: null, finished_at: null, error: null },
      updateStarting: false,
      pollTimer: null,
      showLog: false,
      navStack: [],
    };
  },
  async mounted() {
    try { this.gurus = await get("/api/smart-money/gurus") || []; } catch (e) { console.error(e); this.gurus = []; }
    this.loadTop();
    await this.fetchUpdateStatus();
    if (this.update.status === "running") this.startPolling();
  },
  beforeUnmount() {
    this.stopPolling();
  },
  methods: {
    async searchTicker() {
      const t = (this.tickerQuery || "").trim().toUpperCase();
      if (!t) return;
      this.tickerLoading = true;
      try { this.tickerResult = await get(`/api/smart-money/query/${t}`); }
      catch (e) { console.error(e); this.tickerResult = null; }
      finally { this.tickerLoading = false; }
    },
    async searchGuru() {
      const q = (this.guruQuery || "").trim();
      if (!q) return;
      this.guruLoading = true;
      try { this.guruResult = await get(`/api/smart-money/guru/${encodeURIComponent(q)}`); }
      catch (e) { console.error(e); this.guruResult = null; }
      finally { this.guruLoading = false; }
    },
    async loadTop() {
      this.topLoading = true;
      try { this.top = await get("/api/smart-money/top?limit=30"); }
      catch (e) { console.error(e); this.top = null; }
      finally { this.topLoading = false; }
    },
    pickGuru(name) {
      this.navStack.push({ tab: this.tab, tickerQuery: this.tickerQuery, guruQuery: this.guruQuery });
      this.guruQuery = name;
      this.tab = "guru";
      this.searchGuru();
    },
    pickTicker(ticker) {
      this.navStack.push({ tab: this.tab, tickerQuery: this.tickerQuery, guruQuery: this.guruQuery });
      this.tickerQuery = ticker;
      this.tab = "ticker";
      this.searchTicker();
    },
    goBack() {
      const prev = this.navStack.pop();
      if (!prev) return;
      this.tab = prev.tab;
      this.tickerQuery = prev.tickerQuery;
      this.guruQuery = prev.guruQuery;
      if (prev.tab === "ticker" && prev.tickerQuery) this.searchTicker();
      else if (prev.tab === "guru" && prev.guruQuery) this.searchGuru();
    },
    async fetchUpdateStatus() {
      try {
        const s = await get("/api/smart-money/update/status");
        const wasRunning = this.update.status === "running";
        this.update = s;
        if (wasRunning && s.status !== "running") {
          this.stopPolling();
          this.refreshActiveTab();
        }
      } catch (e) { console.error(e); }
    },
    startPolling() {
      this.stopPolling();
      this.pollTimer = setInterval(this.fetchUpdateStatus, 3000);
    },
    stopPolling() {
      if (this.pollTimer) { clearInterval(this.pollTimer); this.pollTimer = null; }
    },
    async startUpdate() {
      if (this.update.status === "running") return;
      if (!confirm("Refresh smart money data from SEC? This can take several minutes.")) return;
      this.updateStarting = true;
      try {
        const data = await post("/api/smart-money/update");
        this.update = data;
        this.showLog = true;
        this.startPolling();
      } catch (e) {
        alert(`Failed to start update: ${e.message}`);
      } finally {
        this.updateStarting = false;
      }
    },
    refreshActiveTab() {
      if (this.tab === "top") this.loadTop();
      else if (this.tab === "ticker" && this.tickerQuery) this.searchTicker();
      else if (this.tab === "guru" && this.guruQuery) this.searchGuru();
    },
    updateStatusClass() {
      const s = this.update.status;
      if (s === "running") return "badge orange";
      if (s === "done") return "badge green";
      if (s === "error") return "badge red";
      return "badge";
    },
  },
  template: `
    <div>
      <h1>Smart Money</h1>

      <div class="card">
        <div class="toolbar">
          <button class="btn-primary" @click="startUpdate" :disabled="update.status === 'running' || updateStarting">
            {{ update.status === 'running' ? 'Updating...' : 'Update Data (SEC 13F)' }}
          </button>
          <span :class="updateStatusClass()">{{ update.status }}</span>
          <span class="text-muted" v-if="update.started_at">started {{ update.started_at.replace('T',' ').slice(0,19) }}Z</span>
          <span class="text-muted" v-if="update.finished_at && update.status !== 'running'">· finished {{ update.finished_at.replace('T',' ').slice(0,19) }}Z</span>
          <button class="btn-ghost" @click="showLog = !showLog" v-if="update.output && update.output.length">
            {{ showLog ? 'Hide log' : 'Show log' }} ({{ update.output.length }})
          </button>
        </div>
        <pre v-if="showLog && update.output && update.output.length" style="max-height: 240px; overflow: auto; background: #0e1117; padding: 0.6rem; border-radius: 4px; font-size: 0.8rem; margin-top: 0.5rem;">{{ update.output.join('\\n') }}</pre>
        <div v-if="update.error" class="text-red" style="margin-top: 0.4rem;">Error: {{ update.error }}</div>
      </div>

      <div class="subtabs">
        <button :class="{ active: tab === 'ticker' }" @click="tab = 'ticker'">By Ticker</button>
        <button :class="{ active: tab === 'guru' }" @click="tab = 'guru'">By Guru</button>
        <button :class="{ active: tab === 'top' }" @click="tab = 'top'">Top Holdings</button>
      </div>

      <div v-if="tab === 'ticker'">
        <div class="card">
          <div class="toolbar">
            <button class="btn-ghost" v-if="navStack.length" @click="goBack">← Back</button>
            <input type="search" v-model="tickerQuery" @keyup.enter="searchTicker" placeholder="Enter ticker (e.g. AAPL)">
            <button class="btn-primary" @click="searchTicker" :disabled="tickerLoading">
              {{ tickerLoading ? '...' : 'Search' }}
            </button>
          </div>

          <div v-if="tickerResult">
            <h3>
              {{ tickerResult.ticker }}
              <span class="text-muted">— Quarter {{ tickerResult.quarter || 'N/A' }}</span>
            </h3>
            <div v-if="tickerResult.holders.length || tickerResult.exited.length">
              <div class="table-wrap"><table class="table">
                <thead>
                  <tr>
                    <th>Guru</th><th>Firm</th>
                    <th class="num">Shares</th><th class="num">Value</th>
                    <th class="num">Weight</th><th class="num">Δ Weight</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="h in tickerResult.holders" :key="h.name" class="clickable" @click="pickGuru(h.name)">
                    <td>{{ h.name }}</td>
                    <td class="text-muted">{{ h.firm }}</td>
                    <td class="num">{{ fmtNum(h.shares, 0) }}</td>
                    <td class="num">{{ fmtMoney(h.value_usd, { compact: true }) }}</td>
                    <td class="num">{{ h.weight ? h.weight.toFixed(2) + '%' : '—' }}</td>
                    <td class="num" :class="statusClass(h.status)">
                      {{ h.weight_change != null ? (h.weight_change > 0 ? '+' : '') + h.weight_change.toFixed(2) + 'pp' : '—' }}
                    </td>
                    <td><span :class="statusClass(h.status)">{{ h.status }}</span></td>
                  </tr>
                  <tr v-for="e in tickerResult.exited" :key="'x'+e.name" class="clickable" @click="pickGuru(e.name)">
                    <td>{{ e.name }}</td>
                    <td class="text-muted">{{ e.firm }}</td>
                    <td class="num">0</td>
                    <td class="num">—</td>
                    <td class="num text-muted">0.00%</td>
                    <td class="num text-red">{{ e.weight_change != null ? e.weight_change.toFixed(2) + 'pp' : '—' }}</td>
                    <td><span class="text-red">Exited</span></td>
                  </tr>
                </tbody>
              </table></div>
            </div>
            <div class="empty" v-else>No gurus hold {{ tickerResult.ticker }} this quarter.</div>
          </div>
        </div>
      </div>

      <div v-if="tab === 'guru'">
        <div class="card">
          <div class="toolbar">
            <button class="btn-ghost" v-if="navStack.length" @click="goBack">← Back</button>
            <input type="search" v-model="guruQuery" @keyup.enter="searchGuru" placeholder="Guru name (e.g. Buffett, Burry)" list="guru-options">
            <datalist id="guru-options">
              <option v-for="g in gurus" :key="g.id" :value="g.name">{{ g.firm }}</option>
            </datalist>
            <button class="btn-primary" @click="searchGuru" :disabled="guruLoading">
              {{ guruLoading ? '...' : 'Search' }}
            </button>
          </div>

          <div v-if="guruResult && guruResult.guru">
            <h3>
              {{ guruResult.guru.name }}
              <span class="text-muted">— {{ guruResult.guru.firm }} · Quarter {{ guruResult.quarter || 'N/A' }}</span>
            </h3>
            <div class="table-wrap"><table class="table" v-if="guruResult.holdings.length">
              <thead>
                <tr>
                  <th>Ticker</th><th>Issuer</th>
                  <th class="num">Shares</th><th class="num">Value</th>
                  <th class="num">Weight</th><th>Status</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="h in guruResult.holdings" :key="h.ticker" class="clickable" @click="pickTicker(h.ticker)">
                  <td><strong>{{ h.ticker }}</strong></td>
                  <td class="text-muted">{{ h.issuer }}</td>
                  <td class="num">{{ fmtNum(h.shares, 0) }}</td>
                  <td class="num">{{ fmtMoney(h.value_usd, { compact: true }) }}</td>
                  <td class="num" :class="{ 'text-yellow': h.weight >= 5 }">
                    {{ h.weight ? h.weight.toFixed(2) + '%' : '—' }}
                  </td>
                  <td><span :class="statusClass(h.status)">{{ h.status }}</span></td>
                </tr>
              </tbody>
            </table></div>
            <div class="empty" v-else>No holdings found.</div>
          </div>
          <div class="empty" v-else-if="guruQuery">Type a guru name and press Enter.</div>
        </div>
      </div>

      <div v-if="tab === 'top'">
        <div class="card">
          <h3 v-if="top && top.quarter">Top Holdings — Quarter {{ top.quarter }}</h3>
          <div class="loading" v-if="topLoading">Loading...</div>
          <div class="table-wrap" v-else-if="top && top.holdings.length"><table class="table">
            <thead>
              <tr>
                <th>Ticker</th><th>Issuer</th>
                <th class="num"># Gurus</th><th class="num">Total Value</th>
                <th class="num">Avg Weight</th><th class="num">Max Weight</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="h in top.holdings" :key="h.ticker" class="clickable" @click="pickTicker(h.ticker)">
                <td><strong>{{ h.ticker }}</strong></td>
                <td class="text-muted">{{ h.issuer }}</td>
                <td class="num">{{ h.num_gurus }}</td>
                <td class="num">{{ fmtMoney(h.total_value, { compact: true }) }}</td>
                <td class="num">{{ h.avg_weight ? h.avg_weight.toFixed(2) + '%' : '—' }}</td>
                <td class="num" :class="{ 'text-yellow': h.max_weight >= 5 }">
                  {{ h.max_weight ? h.max_weight.toFixed(2) + '%' : '—' }}
                </td>
              </tr>
            </tbody>
          </table></div>
          <div class="empty" v-else>No data available.</div>
        </div>
      </div>
    </div>
  `,
  setup() { return { fmtMoney, fmtNum, statusClass }; },
};
