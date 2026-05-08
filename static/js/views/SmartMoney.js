import { get, fmtMoney, fmtNum, statusClass } from "../utils.js";

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
    };
  },
  async mounted() {
    try { this.gurus = await get("/api/smart-money/gurus") || []; } catch (e) { console.error(e); this.gurus = []; }
    this.loadTop();
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
      this.guruQuery = name;
      this.searchGuru();
    },
  },
  template: `
    <div>
      <h1>Smart Money</h1>

      <div class="subtabs">
        <button :class="{ active: tab === 'ticker' }" @click="tab = 'ticker'">By Ticker</button>
        <button :class="{ active: tab === 'guru' }" @click="tab = 'guru'">By Guru</button>
        <button :class="{ active: tab === 'top' }" @click="tab = 'top'">Top Holdings</button>
      </div>

      <div v-if="tab === 'ticker'">
        <div class="card">
          <div class="toolbar">
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
                  <tr v-for="h in tickerResult.holders" :key="h.name" class="clickable" @click="pickGuru(h.name); tab = 'guru'">
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
                  <tr v-for="e in tickerResult.exited" :key="'x'+e.name" class="clickable" @click="pickGuru(e.name); tab = 'guru'">
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
                <tr v-for="h in guruResult.holdings" :key="h.ticker">
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
              <tr v-for="h in top.holdings" :key="h.ticker">
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
