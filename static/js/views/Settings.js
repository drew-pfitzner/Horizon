import { get, put, post, api } from "../utils.js";

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
      secIdentity: "",
      saving: false,
      savingSec: false,
      message: null,
      messageClass: "",
      secMessage: null,
      secMessageClass: "",
      backupMessage: null,
      backupMessageClass: "",
      importing: false,
      smBackupMessage: null,
      smBackupMessageClass: "",
      smImporting: false,
      sysInfo: null,
      access: null,
      copyMessage: null,
      checkingUpdate: false,
      updating: false,
      sysMessage: null,
      sysMessageClass: "",
      maxPositionPct: 5,
      savingMax: false,
      maxMessage: null,
      maxMessageClass: "",
      fxRates: {},
      fxDraft: { from: "USD", to: "AUD", rate: null },
      savingFx: false,
      refreshingFx: false,
      fxMessage: null,
      fxMessageClass: "",
      ntfy: { ntfy_server: "https://ntfy.sh", ntfy_topic: "", alert_enabled: false, alert_check_time: "16:20" },
      savingNtfy: false,
      testingNtfy: false,
      ntfyMessage: null,
      ntfyMessageClass: "",
    };
  },
  async mounted() {
    await this.load();
    await this.loadSystem();
    await this.loadAccess();
    await this.loadMaxAndFx();
    await this.loadNtfy();
  },
  methods: {
    async loadAccess() {
      try {
        this.access = await get("/api/system/access");
      } catch (e) {
        this.access = null;
      }
    },
    async copyShareUrl() {
      try {
        await navigator.clipboard.writeText(this.shareUrl);
        this.copyMessage = "Copied";
      } catch (e) {
        this.copyMessage = "Copy failed";
      }
      setTimeout(() => { this.copyMessage = null; }, 2000);
    },
    async load() {
      try {
        this.thresholds = await get("/api/settings/pullback-thresholds");
        this.secIdentity = await get("/api/settings/sec-identity");
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
    async saveSec() {
      this.savingSec = true;
      this.secMessage = null;
      try {
        await put("/api/settings/sec-identity", { email: this.secIdentity });
        this.secMessage = "Saved";
        this.secMessageClass = "text-green";
      } catch (e) {
        this.secMessage = `Error: ${e.message}`;
        this.secMessageClass = "text-red";
      } finally {
        this.savingSec = false;
        setTimeout(() => { this.secMessage = null; }, 3000);
      }
    },
    async exportBackup() {
      this.backupMessage = null;
      try {
        const r = await fetch("/api/backup/export");
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const blob = await r.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        const cd = r.headers.get("Content-Disposition") || "";
        const m = cd.match(/filename=([^;]+)/);
        a.href = url;
        a.download = m ? m[1].trim() : `horizon_backup.json`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        this.backupMessage = "Backup downloaded";
        this.backupMessageClass = "text-green";
      } catch (e) {
        this.backupMessage = `Error: ${e.message}`;
        this.backupMessageClass = "text-red";
      } finally {
        setTimeout(() => { this.backupMessage = null; }, 4000);
      }
    },
    triggerImport() {
      this.$refs.importFile.click();
    },
    async importBackup(event) {
      const file = event.target.files && event.target.files[0];
      event.target.value = "";
      if (!file) return;
      if (!confirm("This will OVERWRITE all current Horizon data with the contents of the backup. Continue?")) return;
      this.importing = true;
      this.backupMessage = null;
      try {
        const text = await file.text();
        const data = JSON.parse(text);
        const result = await api("POST", "/api/backup/import", data);
        const counts = result.imported || {};
        const total = Object.values(counts).reduce((a, b) => a + b, 0);
        this.backupMessage = `Imported ${total} rows. Reloading...`;
        this.backupMessageClass = "text-green";
        setTimeout(() => { window.location.reload(); }, 1200);
      } catch (e) {
        this.backupMessage = `Import failed: ${e.message}`;
        this.backupMessageClass = "text-red";
      } finally {
        this.importing = false;
      }
    },
    async exportSmartMoney() {
      this.smBackupMessage = null;
      try {
        const r = await fetch("/api/backup/smart-money/export");
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const blob = await r.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        const cd = r.headers.get("Content-Disposition") || "";
        const m = cd.match(/filename=([^;]+)/);
        a.href = url;
        a.download = m ? m[1].trim() : `smart_money_backup.db`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        this.smBackupMessage = "Smart money backup downloaded";
        this.smBackupMessageClass = "text-green";
      } catch (e) {
        this.smBackupMessage = `Error: ${e.message}`;
        this.smBackupMessageClass = "text-red";
      } finally {
        setTimeout(() => { this.smBackupMessage = null; }, 4000);
      }
    },
    triggerSmartMoneyImport() {
      this.$refs.smImportFile.click();
    },
    async importSmartMoney(event) {
      const file = event.target.files && event.target.files[0];
      event.target.value = "";
      if (!file) return;
      if (!confirm("This will OVERWRITE the current smart money database with the uploaded file. Continue?")) return;
      this.smImporting = true;
      this.smBackupMessage = null;
      try {
        const form = new FormData();
        form.append("file", file);
        const r = await fetch("/api/backup/smart-money/import", { method: "POST", body: form });
        const body = await r.json();
        if (!r.ok || !body.success) throw new Error(body.error || `HTTP ${r.status}`);
        this.smBackupMessage = "Smart money restored. Reloading...";
        this.smBackupMessageClass = "text-green";
        setTimeout(() => { window.location.reload(); }, 1200);
      } catch (e) {
        this.smBackupMessage = `Import failed: ${e.message}`;
        this.smBackupMessageClass = "text-red";
      } finally {
        this.smImporting = false;
      }
    },
    async loadSystem() {
      try {
        this.sysInfo = await get("/api/system/info");
      } catch (e) {
        this.sysInfo = { git_available: false, message: `Error: ${e.message}` };
      }
    },
    async checkForUpdate() {
      this.checkingUpdate = true;
      this.sysMessage = null;
      try {
        this.sysInfo = await post("/api/system/check");
        this.sysMessage = this.sysInfo.behind
          ? `${this.sysInfo.behind} update${this.sysInfo.behind === 1 ? "" : "s"} available`
          : "Already up to date";
        this.sysMessageClass = "text-green";
      } catch (e) {
        this.sysMessage = `Error: ${e.message}`;
        this.sysMessageClass = "text-red";
      } finally {
        this.checkingUpdate = false;
        setTimeout(() => { this.sysMessage = null; }, 4000);
      }
    },
    async runUpdate() {
      if (!confirm("Pull latest changes and restart Horizon? The app will be unreachable for a few seconds.")) return;
      this.updating = true;
      this.sysMessage = "Pulling latest…";
      this.sysMessageClass = "";
      try {
        const result = await post("/api/system/update");
        if (!result.restarting) {
          this.sysMessage = result.message || "Already up to date";
          this.sysMessageClass = "text-green";
          this.updating = false;
          return;
        }
        const note = result.deps_changed
          ? " (requirements.txt changed — run update.sh from host to fully rebuild)"
          : result.image_changed
            ? " (Dockerfile/compose changed — run update.sh from host to rebuild)"
            : "";
        this.sysMessage = `Updated ${result.before}→${result.after}. Restarting…${note}`;
        this.sysMessageClass = "text-green";
        await this.waitForRestart(result.after);
      } catch (e) {
        this.sysMessage = `Update failed: ${e.message}`;
        this.sysMessageClass = "text-red";
        this.updating = false;
      }
    },
    async waitForRestart(targetSha) {
      const start = Date.now();
      const timeoutMs = 90_000;
      while (Date.now() - start < timeoutMs) {
        await new Promise(r => setTimeout(r, 2000));
        try {
          const info = await get("/api/system/info");
          if (info && info.full_sha && info.full_sha.startsWith(targetSha)) {
            this.sysMessage = "Restart complete. Reloading…";
            setTimeout(() => window.location.reload(), 700);
            return;
          }
        } catch (e) { /* still down */ }
      }
      this.sysMessage = "Restart taking longer than expected — reload manually if needed.";
      this.sysMessageClass = "text-red";
      this.updating = false;
    },
    async loadMaxAndFx() {
      try {
        this.maxPositionPct = Number(await get("/api/settings/max-position-pct")) || 5;
        this.fxRates = await get("/api/settings/fx-rates") || {};
      } catch (e) { console.error(e); }
    },
    async saveMax() {
      this.savingMax = true;
      this.maxMessage = null;
      try {
        const v = await put("/api/settings/max-position-pct", { value: Number(this.maxPositionPct) });
        this.maxPositionPct = Number(v);
        this.maxMessage = "Saved";
        this.maxMessageClass = "text-green";
      } catch (e) {
        this.maxMessage = `Error: ${e.message}`;
        this.maxMessageClass = "text-red";
      } finally {
        this.savingMax = false;
        setTimeout(() => { this.maxMessage = null; }, 3000);
      }
    },
    fxEntries() {
      return Object.entries(this.fxRates).map(([k, v]) => ({ pair: k, ...v }));
    },
    async refreshFx() {
      this.refreshingFx = true;
      this.fxMessage = null;
      try {
        await post("/api/settings/fx-rates/refresh", {
          from: (this.fxDraft.from || "USD").toUpperCase(),
          to: (this.fxDraft.to || "AUD").toUpperCase(),
        });
        this.fxRates = await get("/api/settings/fx-rates") || {};
        this.fxMessage = "Refreshed from open.er-api.com";
        this.fxMessageClass = "text-green";
      } catch (e) {
        this.fxMessage = `Error: ${e.message}`;
        this.fxMessageClass = "text-red";
      } finally {
        this.refreshingFx = false;
        setTimeout(() => { this.fxMessage = null; }, 4000);
      }
    },
    async saveFxOverride() {
      if (!this.fxDraft.rate || this.fxDraft.rate <= 0) {
        this.fxMessage = "Enter a positive rate";
        this.fxMessageClass = "text-red";
        return;
      }
      this.savingFx = true;
      this.fxMessage = null;
      try {
        await put("/api/settings/fx-rates", {
          from: (this.fxDraft.from || "USD").toUpperCase(),
          to: (this.fxDraft.to || "AUD").toUpperCase(),
          rate: Number(this.fxDraft.rate),
        });
        this.fxRates = await get("/api/settings/fx-rates") || {};
        this.fxDraft.rate = null;
        this.fxMessage = "Manual override saved";
        this.fxMessageClass = "text-green";
      } catch (e) {
        this.fxMessage = `Error: ${e.message}`;
        this.fxMessageClass = "text-red";
      } finally {
        this.savingFx = false;
        setTimeout(() => { this.fxMessage = null; }, 3000);
      }
    },
    async loadNtfy() {
      try {
        const s = await get("/api/alerts/settings");
        this.ntfy = {
          ntfy_server: s.ntfy_server, ntfy_topic: s.ntfy_topic,
          alert_enabled: s.alert_enabled, alert_check_time: s.alert_check_time,
        };
      } catch (e) { console.error(e); }
    },
    async saveNtfy() {
      this.savingNtfy = true;
      this.ntfyMessage = null;
      try {
        await put("/api/alerts/settings", this.ntfy);
        this.ntfyMessage = "Saved";
        this.ntfyMessageClass = "text-green";
      } catch (e) {
        this.ntfyMessage = `Error: ${e.message}`;
        this.ntfyMessageClass = "text-red";
      } finally {
        this.savingNtfy = false;
        setTimeout(() => { this.ntfyMessage = null; }, 3000);
      }
    },
    async testNtfy() {
      this.testingNtfy = true;
      this.ntfyMessage = null;
      try {
        await post("/api/alerts/test", {});
        this.ntfyMessage = "Test push sent — check your phone";
        this.ntfyMessageClass = "text-green";
      } catch (e) {
        this.ntfyMessage = `Test failed: ${e.message}`;
        this.ntfyMessageClass = "text-red";
      } finally {
        this.testingNtfy = false;
        setTimeout(() => { this.ntfyMessage = null; }, 4000);
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
    lastUpdated() {
      const d = this.sysInfo && this.sysInfo.date;
      if (!d) return null;
      const dt = new Date(d);
      if (isNaN(dt)) return null;
      return dt.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
    },
    // Address other devices on the same network can use to reach this server.
    // If you already reached the app via a real network address, that same URL
    // works for other devices — so just use the current origin. Only when you're
    // on localhost do we fall back to the server-detected LAN IP.
    shareUrl() {
      const loc = window.location;
      const isLocal = /^(localhost|127\.|0\.0\.0\.0|\[?::1\]?)$/.test(loc.hostname);
      if (!isLocal) return loc.origin;
      const ip = this.access && this.access.lan_ip;
      if (!ip) return null;
      const port = loc.port ? `:${loc.port}` : "";
      return `${loc.protocol}//${ip}${port}`;
    },
    qrSvg() {
      if (!this.shareUrl || typeof window.qrcode !== "function") return null;
      try {
        const qr = window.qrcode(0, "M");   // 0 = auto-size, M = medium error correction
        qr.addData(this.shareUrl);
        qr.make();
        return qr.createSvgTag({ cellSize: 6, margin: 12, scalable: true });
      } catch (e) {
        return null;
      }
    },
  },
  template: `
    <div>
      <h1>Settings</h1>

      <div class="grid-2">
      <div class="card">
        <h3>Connect from your phone</h3>
        <template v-if="shareUrl">
          <p class="text-muted">
            On the same Wi-Fi network, scan this QR code (or open the link) to load Horizon on another device.
          </p>
          <div style="display: flex; align-items: center; gap: 1.25rem; flex-wrap: wrap;">
            <div v-if="qrSvg" v-html="qrSvg"
                 style="width: 180px; height: 180px; background: #fff; padding: 8px; border-radius: 8px; flex-shrink: 0;"></div>
            <div>
              <div style="font-family: monospace; font-size: 1.05rem; margin-bottom: 0.6rem;">{{ shareUrl }}</div>
              <div class="toolbar">
                <button class="btn-ghost" @click="copyShareUrl">Copy Link</button>
                <span class="text-green">{{ copyMessage }}</span>
              </div>
              <p class="text-muted" style="font-size: 0.8rem; margin: 0.5rem 0 0;">
                Not connecting? Both devices must be on the same network. Over Tailscale, use your Tailscale IP instead.
              </p>
            </div>
          </div>
        </template>
        <div class="text-muted" v-else>
          <p style="margin-top: 0;">Couldn't determine a shareable network address.</p>
          <p style="font-size: 0.85rem; margin-bottom: 0;" v-if="access && access.in_docker">
            You're viewing this via <code>localhost</code> inside Docker, so the app can't see your computer's
            network IP. Either open Horizon using your computer's IP (then this QR fills in automatically), or set
            <code>HORIZON_HOST_IP</code> to your computer's address when starting the container.
          </p>
          <p style="font-size: 0.85rem; margin-bottom: 0;" v-else>
            Open Horizon using your computer's network IP and this QR code will fill in automatically.
          </p>
        </div>
      </div>

      <div class="card" v-if="sysInfo">
        <h3>App Updates</h3>
        <p class="text-muted" v-if="!sysInfo.git_available">Automatic updates aren't available for this install.</p>
        <div v-else>
          <div style="margin-bottom: 1rem;">
            <div v-if="sysInfo.behind > 0" class="text-green" style="font-weight: 600; font-size: 1.05rem;">
              {{ sysInfo.behind }} update{{ sysInfo.behind === 1 ? '' : 's' }} available
            </div>
            <div v-else style="font-weight: 600; font-size: 1.05rem;">✓ Horizon is up to date</div>
            <div class="text-muted" style="font-size: 0.85rem; margin-top: 0.3rem;" v-if="lastUpdated">
              Last updated {{ lastUpdated }}
            </div>
            <div class="text-muted" style="font-size: 0.85rem; margin-top: 0.3rem;" v-if="sysInfo.dirty">
              Some local files have changed — automatic update is paused to avoid overwriting them.
            </div>
          </div>
          <div class="toolbar">
            <button class="btn-ghost" :disabled="checkingUpdate || updating" @click="checkForUpdate">
              {{ checkingUpdate ? "Checking…" : "Check for Updates" }}
            </button>
            <button class="btn-primary"
                    :disabled="updating || sysInfo.dirty || !sysInfo.behind"
                    @click="runUpdate">
              {{ updating ? "Updating…" : (sysInfo.behind ? "Update & Restart" : "Up to date") }}
            </button>
            <span :class="sysMessageClass">{{ sysMessage }}</span>
          </div>
        </div>
      </div>
      </div>

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
        <h3>SEC Identity (Smart Money Updates)</h3>
        <p class="text-muted">
          Provide your email address for SEC Edgar access. This is required to update the smart money guru holdings database.
        </p>
        <div style="margin-bottom: 1rem;">
          <label>Email Address</label>
          <input type="email" v-model="secIdentity" placeholder="your.email@example.com" style="width: 100%; max-width: 300px;">
        </div>
        <div class="toolbar">
          <button class="btn-primary" :disabled="savingSec" @click="saveSec">
            {{ savingSec ? "Saving..." : "Save SEC Email" }}
          </button>
          <span :class="secMessageClass">{{ secMessage }}</span>
        </div>
      </div>

      <div class="card">
        <h3>Alert Notifications (ntfy)</h3>
        <p class="text-muted">
          Push buy/sell alerts to your phone. Install the <strong>ntfy</strong> app, subscribe to your topic,
          and Horizon posts signals to it. Public ntfy.sh topics are readable by anyone who knows the name —
          use a long random topic, or self-host ntfy.
        </p>
        <div class="settings-fields">
          <div class="field">
            <label>ntfy server</label>
            <input type="text" v-model="ntfy.ntfy_server" placeholder="https://ntfy.sh">
          </div>
          <div class="field">
            <label>Topic</label>
            <input type="text" v-model="ntfy.ntfy_topic" placeholder="horizon-<long-random>">
          </div>
          <div class="field">
            <label>Daily check time (US/Eastern)</label>
            <input type="text" v-model="ntfy.alert_check_time" placeholder="16:20" style="max-width: 8rem;">
          </div>
        </div>
        <label class="check-inline">
          <input type="checkbox" v-model="ntfy.alert_enabled"> Alerts enabled
        </label>
        <div class="toolbar">
          <button class="btn-primary" :disabled="savingNtfy" @click="saveNtfy">
            {{ savingNtfy ? "Saving…" : "Save" }}
          </button>
          <button class="btn-ghost" :disabled="testingNtfy" @click="testNtfy">
            {{ testingNtfy ? "Sending…" : "Send test push" }}
          </button>
          <span :class="ntfyMessageClass">{{ ntfyMessage }}</span>
        </div>
      </div>

      <div class="card">
        <h3>Position Sizing</h3>
        <p class="text-muted">
          Maximum allowed position size as a percent of your portfolio. Trades above this threshold are flagged in amber on the Trades tab.
        </p>
        <div class="toolbar">
          <label style="margin: 0;">Max Position %</label>
          <input type="number" step="0.1" min="0.1" max="100" v-model.number="maxPositionPct" style="width: 100px;">
          <button class="btn-primary" :disabled="savingMax" @click="saveMax">
            {{ savingMax ? "Saving..." : "Save" }}
          </button>
          <span :class="maxMessageClass">{{ maxMessage }}</span>
        </div>
      </div>

      <div class="card">
        <h3>Currency Conversion</h3>
        <p class="text-muted">
          FX rates are fetched automatically from open.er-api.com (free, no key) and cached per day.
          You can also override any rate manually below — manual rates take priority over fetched ones.
        </p>
        <div class="toolbar" style="flex-wrap: wrap; gap: .5rem;">
          <label style="margin: 0;">From</label>
          <input type="text" v-model="fxDraft.from" style="width: 70px; text-transform: uppercase;">
          <label style="margin: 0;">To</label>
          <input type="text" v-model="fxDraft.to" style="width: 70px; text-transform: uppercase;">
          <label style="margin: 0;">Rate</label>
          <input type="number" step="0.0001" v-model.number="fxDraft.rate" style="width: 110px;" placeholder="manual rate">
          <button class="btn-ghost" :disabled="refreshingFx" @click="refreshFx">
            {{ refreshingFx ? "Fetching…" : "Fetch Live" }}
          </button>
          <button class="btn-primary" :disabled="savingFx" @click="saveFxOverride">
            {{ savingFx ? "Saving…" : "Save Manual Rate" }}
          </button>
          <span :class="fxMessageClass">{{ fxMessage }}</span>
        </div>
        <div v-if="fxEntries().length" class="table-wrap" style="margin-top: 1rem;">
          <table class="table">
            <thead>
              <tr><th>Pair</th><th class="num">Rate</th><th>Source</th><th>Updated</th></tr>
            </thead>
            <tbody>
              <tr v-for="e in fxEntries()" :key="e.pair">
                <td><strong>{{ e.pair.replace('_', ' → ') }}</strong></td>
                <td class="num">{{ Number(e.rate).toFixed(4) }}</td>
                <td>{{ e.source }}</td>
                <td class="text-muted">{{ e.updated_at }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="card">
        <h3>Data Backup</h3>
        <p class="text-muted">
          Export a full JSON backup of all Horizon data (market checks, valuations, research, trades, settings).
          Run before updates so you can restore if anything goes wrong.
        </p>
        <div class="toolbar">
          <button class="btn-primary" @click="exportBackup">Export Backup</button>
          <button class="btn-ghost" :disabled="importing" @click="triggerImport">
            {{ importing ? "Importing..." : "Import Backup" }}
          </button>
          <input type="file" accept="application/json,.json" ref="importFile" @change="importBackup" style="display:none;">
          <span :class="backupMessageClass">{{ backupMessage }}</span>
        </div>
      </div>

      <div class="card">
        <h3>Smart Money Backup</h3>
        <p class="text-muted">
          Export or restore the smart money database (SEC 13F guru holdings). Useful when moving to a new machine
          so you don't have to re-run the full SEC refresh.
        </p>
        <div class="toolbar">
          <button class="btn-primary" @click="exportSmartMoney">Export Smart Money</button>
          <button class="btn-ghost" :disabled="smImporting" @click="triggerSmartMoneyImport">
            {{ smImporting ? "Importing..." : "Import Smart Money" }}
          </button>
          <input type="file" accept=".db,application/octet-stream" ref="smImportFile" @change="importSmartMoney" style="display:none;">
          <span :class="smBackupMessageClass">{{ smBackupMessage }}</span>
        </div>
      </div>
    </div>
  `,
};
