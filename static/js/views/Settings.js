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
      checkingUpdate: false,
      updating: false,
      sysMessage: null,
      sysMessageClass: "",
    };
  },
  async mounted() {
    await this.load();
    await this.loadSystem();
  },
  methods: {
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

      <div class="card" v-if="sysInfo">
        <h3>App Updates</h3>
        <p class="text-muted" v-if="!sysInfo.git_available">{{ sysInfo.message }}</p>
        <div v-else>
          <div class="text-muted" style="margin-bottom: .5rem;">
            Branch: <strong>{{ sysInfo.branch }}</strong> ·
            Current: <code>{{ sysInfo.sha }}</code>
            <span v-if="sysInfo.dirty" class="text-red"> (uncommitted changes)</span>
            <span v-if="sysInfo.has_upstream && sysInfo.behind > 0" class="text-green">
              · {{ sysInfo.behind }} behind origin
            </span>
            <span v-if="sysInfo.has_upstream && sysInfo.behind === 0" class="text-muted"> · up to date</span>
          </div>
          <div v-if="sysInfo.dirty && sysInfo.dirty_files && sysInfo.dirty_files.length"
               class="text-muted" style="margin-bottom: .5rem; font-family: monospace; font-size: .85em;">
            <div>Dirty files (blocking update):</div>
            <div v-for="f in sysInfo.dirty_files" :key="f">&nbsp;&nbsp;{{ f }}</div>
          </div>
          <div class="text-muted" style="margin-bottom: 1rem;">
            Latest commit: <em>{{ sysInfo.subject }}</em>
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
