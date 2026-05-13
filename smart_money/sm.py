#!/usr/bin/env python3
"""Smart Money Tracker -- Full-screen Terminal UI."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Center, Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    DataTable, Footer, Header, Input, Label,
    LoadingIndicator, OptionList, ProgressBar, Static,
)
from textual.widgets.option_list import Option
from textual import on, work

from rich.text import Text


# ── Helpers ──────────────────────────────────────────────────────────────

_BANNER_ROWS = [
    " ██████  ███    ███  █████  ██████  ████████",
    "██       ████  ████ ██   ██ ██   ██    ██   ",
    " █████   ██ ████ ██ ███████ ██████     ██   ",
    "     ██  ██  ██  ██ ██   ██ ██   ██    ██   ",
    " ██████  ██      ██ ██   ██ ██   ██    ██   ",
    "███    ███  ██████  ███    ██ ██████ ██    ██",
    "████  ████ ██    ██ ████   ██ ██      ██  ██ ",
    "██ ████ ██ ██    ██ ██ ██  ██ ████     ████  ",
    "██  ██  ██ ██    ██ ██  ██ ██ ██        ██   ",
    "██      ██  ██████  ██   ████ ██████    ██   ",
]
_BANNER_COLORS = [
    "#00e5ff", "#00ccf0", "#00b3e0", "#009ad0", "#0080c0",
    "#1a60d0", "#3340e0", "#4d20f0", "#6600e0", "#8000c0",
]
BANNER = "\n".join(
    f"[bold {c}]{r}[/]" for c, r in zip(_BANNER_COLORS, _BANNER_ROWS)
) + "\n[dim]━━━━━━━━━━━━━━━━━ 13F Filing Tracker ━━━━━━━━━━━━━━━━━[/dim]"


def _qlabel(quarter_str):
    if not quarter_str:
        return "?"
    try:
        y, m = quarter_str.split("-")[0], int(quarter_str.split("-")[1])
        return f"{({3:1,6:2,9:3,12:4}.get(m,'?'))} {y}"
    except Exception:
        return quarter_str


def _fval(v):
    if not v: return "--"
    if v >= 1e9: return f"${v/1e9:.2f}B"
    if v >= 1e6: return f"${v/1e6:.1f}M"
    if v >= 1e3: return f"${v/1e3:.0f}K"
    return f"${v}"


def _fshares(s):
    if not s: return "--"
    if s >= 1e6: return f"{s/1e6:.2f}M"
    if s >= 1e3: return f"{s/1e3:.1f}K"
    return str(s)


def _fwt(w):
    return f"{w:.2f}%" if w is not None else "--"


def _styled_wt(w):
    t = Text(_fwt(w))
    if w and w >= 5: t.stylize("bold green")
    elif w and w >= 2: t.stylize("yellow")
    else: t.stylize("dim")
    return t


def _styled_change(status, wc=None):
    if status == "New":
        return Text("NEW", style="bold green")
    if status == "Exited":
        if wc is not None:
            return Text(f"EXITED (was {abs(wc):.2f}%)", style="bold red")
        return Text("EXITED", style="bold red")
    if status == "Unchanged":
        return Text("Unchanged", style="dim")
    if wc is not None:
        sign = "+" if wc > 0 else ""
        color = "green" if status == "Increased" else "red"
        return Text(f"{status} ({sign}{wc:.2f}pp of portfolio)", style=color)
    return Text(status)


def _styled_qoq(status):
    s = {"New": "bold green", "Increased": "green", "Decreased": "red", "Exited": "bold red"}
    return Text(status, style=s.get(status, "dim"))


def _db_stats():
    try:
        from smart_money.db import get_db
        with get_db() as conn:
            gurus = conn.execute("SELECT COUNT(*) c FROM gurus WHERE active=1").fetchone()["c"]
            holdings = conn.execute("SELECT COUNT(*) c FROM holdings").fetchone()["c"]
            latest = conn.execute("SELECT MAX(report_period) q FROM holdings").fetchone()["q"]
        return gurus, holdings, latest
    except Exception:
        return None, None, None


# ── Input Modal ──────────────────────────────────────────────────────────

class InputModal(ModalScreen[str]):
    """Centered modal that prompts for a text value."""

    DEFAULT_CSS = """
    InputModal {
        align: center middle;
    }
    #dialog {
        width: 60;
        height: auto;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }
    #dialog-label {
        text-align: center;
        text-style: bold;
        color: $accent;
        width: 100%;
        margin-bottom: 1;
    }
    """

    def __init__(self, title: str, placeholder: str = "") -> None:
        super().__init__()
        self._title = title
        self._ph = placeholder

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self._title, id="dialog-label")
            yield Input(placeholder=self._ph)

    @on(Input.Submitted)
    def _submit(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    def key_escape(self) -> None:
        self.dismiss("")


# ── Main App ─────────────────────────────────────────────────────────────

class SmartMoneyApp(App):
    """Full-screen Smart Money terminal interface."""

    TITLE = "Smart Money"
    theme = "nord"

    DEFAULT_CSS = """
    Screen {
        background: $surface;
    }

    #content {
        width: 100%;
        height: 1fr;
    }

    /* ── Home ── */
    .banner {
        text-align: center;
        width: 100%;
        margin: 1 0 0 0;
    }
    .menu-area {
        width: 100%;
        height: 1fr;
        align: center middle;
    }
    .menu {
        width: 30;
        height: auto;
        border: round $accent;
    }
    OptionList > .option-list--option-highlighted {
        background: $accent;
    }

    /* ── Results ── */
    .results-title {
        text-align: center;
        text-style: bold;
        color: $accent;
        width: 100%;
        padding: 1 1 0 1;
    }
    .results-summary {
        text-align: center;
        color: $text-muted;
        width: 100%;
        padding: 0 1;
    }
    DataTable {
        height: 1fr;
        margin: 0 1;
    }

    /* ── Loading / Update progress ── */
    .loading-msg {
        text-align: center;
        color: $text-muted;
        width: 100%;
        margin-top: 1;
    }
    LoadingIndicator {
        height: 3;
    }
    .update-progress {
        text-align: center;
        width: 100%;
        padding: 0 4;
        margin-top: 1;
    }
    #update-bar-wrap {
        width: 100%;
        height: auto;
        align-horizontal: center;
        margin-top: 1;
    }
    ProgressBar {
        width: auto;
    }
    ProgressBar Bar {
        width: 60;
    }
    """

    BINDINGS = [
        Binding("q", "query", "Query", show=True),
        Binding("p", "portfolio", "Portfolio", show=True),
        Binding("t", "top", "Top", show=True),
        Binding("g", "gurus", "Gurus", show=True),
        Binding("u", "update_data", "Update", show=True),
        Binding("s", "settings", "Settings", show=True),
        Binding("escape", "go_home", "Back", show=True),
        Binding("h", "force_home", "Home", show=True),
        Binding("ctrl+c", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._view = "home"
        self._table_data: list = []  # stores row context for drill-down
        self._history: list = []  # stack of (view_name, cursor_row, params) for back nav
        self._query_param: str = ""
        self._portfolio_param: str = ""
        # Update state (persists across view navigation)
        self._update_running = False
        self._update_current = 0
        self._update_total = 0
        self._update_guru = ""
        self._update_status = ""  # fetching/ok/skipped/error/done/failed

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Container(id="content")
        yield Footer()

    def on_mount(self) -> None:
        gurus, holdings, latest = _db_stats()
        if gurus and latest:
            self.sub_title = f"{gurus} gurus | {holdings:,} holdings | Latest: Q{_qlabel(latest)}"
        self._go_home()
        self._check_sec_identity()

    # ── Home view ────────────────────────────────────────────────────

    def _go_home(self) -> None:
        self._view = "home"
        self._table_data = []
        self._history.clear()
        c = self.query_one("#content")
        c.remove_children()
        c.mount(
            Static(BANNER, classes="banner"),
            Container(
                OptionList(
                    Option("  Query Stock         q ", id="query"),
                    Option("  Guru Portfolio      p ", id="portfolio"),
                    Option("  Top Holdings        t ", id="top"),
                    Option("  All Gurus           g ", id="gurus"),
                    Option("  ───────────────────── ", disabled=True),
                    Option("  Update from SEC     u ", id="update"),
                    Option("  Settings            s ", id="settings"),
                    classes="menu",
                ),
                classes="menu-area",
            ),
        )
        self.set_timer(0.1, self._focus_menu)

    def _focus_menu(self) -> None:
        try:
            self.query_one(".menu").focus()
        except Exception:
            pass

    # ── Generic results view ─────────────────────────────────────────

    def _show_table(self, title, columns, rows, summary=""):
        c = self.query_one("#content")
        c.remove_children()

        table = DataTable(cursor_type="row")
        parts = [Static(title, classes="results-title"), table]
        if summary:
            parts.append(Static(summary, classes="results-summary"))
        c.mount(*parts)

        for col in columns:
            table.add_column(col, key=col)
        for row in rows:
            table.add_row(*row)

        table.focus()

    # ── Menu selection (Enter key) ───────────────────────────────────

    @on(OptionList.OptionSelected)
    def _menu_pick(self, event: OptionList.OptionSelected) -> None:
        actions = {
            "query": self.action_query,
            "portfolio": self.action_portfolio,
            "top": self.action_top,
            "gurus": self.action_gurus,
            "update": self.action_update_data,
            "settings": self.action_settings,
        }
        fn = actions.get(event.option.id)
        if fn:
            fn()

    # ── Drill-down from results table ─────────────────────────────────

    @on(DataTable.RowSelected)
    def _table_drill(self, event: DataTable.RowSelected) -> None:
        idx = event.cursor_row
        if idx < 0 or idx >= len(self._table_data):
            return
        entry = self._table_data[idx]
        if not entry:
            return
        params = self._current_params()
        self._history.append((self._view, idx, params))
        if self._view in ("gurus", "query"):
            self._run_portfolio(entry)
        elif self._view in ("top", "portfolio"):
            self._run_query(entry)
        else:
            self._history.pop()

    def _current_params(self):
        if self._view == "query":
            return self._query_param
        if self._view == "portfolio":
            return self._portfolio_param
        return None

    # ── Query ────────────────────────────────────────────────────────

    def action_query(self) -> None:
        self.push_screen(InputModal("Enter ticker symbol", "AAPL"), self._run_query)

    def _run_query(self, ticker: str) -> None:
        if not ticker:
            return
        self._table_data = []
        try:
            from smart_money.analyzer import get_holders_of_ticker
            results, quarter = get_holders_of_ticker(ticker)
        except Exception as e:
            self.notify(str(e), severity="error"); return
        if results is None:
            self.notify(f"No data for {ticker.upper()}", severity="warning"); return

        self._view = "query"
        self._query_param = ticker
        active = [r for r in results if r["status"] != "Exited"]
        avg = (sum(r["weight"] for r in active if r["weight"]) / len(active)) if active else 0

        rows = []
        for i, r in enumerate(results, 1):
            self._table_data.append(r["name"])
            rows.append((
                str(i), r["name"], r["firm"],
                _styled_wt(r["weight"]), _fshares(r["shares"]),
                _fval(r["value_usd"]),
                _styled_change(r["status"], r.get("weight_change")),
            ))

        self._show_table(
            f"{ticker.upper()}  --  Q{_qlabel(quarter)}",
            ["#", "Guru", "Firm", "Weight", "Shares", "Value", "QoQ Change"],
            rows,
            summary=f"{len(active)} guru(s) holding  |  Avg weight: {avg:.2f}%",
        )

    # ── Portfolio ────────────────────────────────────────────────────

    def action_portfolio(self) -> None:
        self.push_screen(InputModal("Enter guru name", "Buffett"), self._run_portfolio)

    def _run_portfolio(self, name: str) -> None:
        if not name:
            return
        self._table_data = []
        try:
            from smart_money.analyzer import get_guru_portfolio
            guru, quarter, holdings = get_guru_portfolio(name)
        except Exception as e:
            self.notify(str(e), severity="error"); return
        if guru is None:
            self.notify(f"No guru matching '{name}'", severity="warning"); return
        if holdings is None:
            self.notify(f"No holdings for {guru['name']}", severity="warning"); return

        self._view = "portfolio"
        self._portfolio_param = name
        rows = []
        for i, h in enumerate(holdings, 1):
            t = (h["ticker"] or "").strip()
            # Skip CUSIP fallbacks (9 chars, alphanumeric) — only real tickers drill-down
            self._table_data.append(t if t and len(t) <= 6 else "")
            rows.append((
                str(i), h["ticker"] or "???", h["issuer"][:35],
                _styled_wt(h["weight"]), _fshares(h["shares"]),
                _fval(h["value_usd"]), _styled_qoq(h["status"]),
            ))

        self._show_table(
            f"{guru['name']} ({guru['firm']})  --  Q{_qlabel(quarter)}",
            ["#", "Ticker", "Issuer", "Weight", "Shares", "Value", "QoQ"],
            rows,
            summary=f"{len(holdings)} holdings",
        )

    # ── Top ──────────────────────────────────────────────────────────

    def action_top(self) -> None:
        try:
            from smart_money.analyzer import get_top_held
            results, quarter = get_top_held(limit=30)
        except Exception as e:
            self.notify(str(e), severity="error"); return
        if results is None:
            self.notify("No data found", severity="warning"); return

        self._table_data = [r["ticker"] for r in results]
        rows = []
        for i, r in enumerate(results, 1):
            gc = Text(str(r["num_gurus"]),
                      style="bold yellow" if r["num_gurus"] >= 10 else "bold")
            rows.append((
                str(i), r["ticker"] or "???", (r["issuer"] or "")[:35],
                gc, _fwt(r["avg_weight"]), _fwt(r["max_weight"]),
                _fval(r["total_value"]),
            ))

        self._view = "top"
        self._show_table(
            f"Top Held Stocks  --  Q{_qlabel(quarter)}",
            ["#", "Ticker", "Issuer", "# Gurus", "Avg Wt%", "Max Wt%", "Total Value"],
            rows,
        )

    # ── Gurus ────────────────────────────────────────────────────────

    def action_gurus(self) -> None:
        try:
            from smart_money.gurus import list_gurus
            gurus = list_gurus(show_all=False)
        except Exception as e:
            self.notify(str(e), severity="error"); return

        self._table_data = [g["name"] for g in gurus]
        rows = []
        for i, g in enumerate(gurus, 1):
            status = (Text("Active", style="green") if g["active"]
                      else Text(g["notes"] or "Inactive", style="dim red"))
            rows.append((
                str(i), g["name"], g["firm"],
                g["cik"] or "--", status, g["last_updated"] or "--",
            ))

        self._view = "gurus"
        self._show_table(
            f"Active Gurus ({len(gurus)})",
            ["#", "Name", "Firm", "CIK", "Status", "Last Updated"],
            rows,
        )

    # ── Update ───────────────────────────────────────────────────────

    def action_update_data(self) -> None:
        if self._update_running:
            # Already running — just show the progress view
            self._show_update_view()
            return
        self._update_running = True
        self._update_current = 0
        self._update_total = 0
        self._update_guru = ""
        self._update_status = "starting"
        self._show_update_view()
        self._do_update()

    def _show_update_view(self) -> None:
        self._view = "updating"
        c = self.query_one("#content")
        c.remove_children()
        c.mount(
            Static("Updating from SEC EDGAR...", classes="results-title"),
            Static("", id="update-guru", classes="update-progress"),
            Center(
                ProgressBar(total=100, show_eta=False, id="update-bar"),
                id="update-bar-wrap",
            ),
            Static("", id="update-detail", classes="update-progress"),
            Static("[dim]Press Esc to return home — update continues in background.[/dim]",
                   classes="loading-msg"),
        )
        # Restore current progress if already running
        if self._update_total > 0:
            self._refresh_progress_ui()

    def _update_progress(self, current: int, total: int, guru: str, status: str) -> None:
        self._update_current = current
        self._update_total = total
        self._update_guru = guru
        self._update_status = status
        self.call_from_thread(self._refresh_progress_ui)

    def _refresh_progress_ui(self) -> None:
        if self._view != "updating":
            return
        try:
            bar = self.query_one("#update-bar", ProgressBar)
            bar.update(total=self._update_total, progress=self._update_current)
            guru_label = self.query_one("#update-guru", Static)
            status_icon = {"fetching": "⟳", "ok": "✓", "skipped": "−", "error": "✗",
                           "starting": "…", "resolving": "⟳"}.get(self._update_status, "")
            guru_label.update(f"{status_icon} [{self._update_current}/{self._update_total}] {self._update_guru}")
            detail = self.query_one("#update-detail", Static)
            pct = (self._update_current / self._update_total * 100) if self._update_total else 0
            detail.update(f"[dim]{pct:.0f}% complete[/dim]")
        except Exception:
            pass

    @work(thread=True)
    def _do_update(self) -> None:
        import io, contextlib
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                from smart_money.fetcher import fetch_all_gurus
                from smart_money.cusip_mapper import resolve_unmapped_tickers, apply_cached_tickers
                fetch_all_gurus(num_quarters=1, progress_callback=self._update_progress)
                self._update_status = "resolving"
                self._update_guru = "Resolving tickers..."
                self.call_from_thread(self._refresh_progress_ui)
                apply_cached_tickers()
                resolve_unmapped_tickers()
            self._update_running = False
            self._update_status = "done"
            self.call_from_thread(self.notify, "Update complete!", severity="information")
        except Exception as e:
            self._update_running = False
            self._update_status = "failed"
            self.call_from_thread(self.notify, f"Update failed: {e}", severity="error")
        # Refresh subtitle with new stats
        gurus, holdings, latest = _db_stats()
        if gurus and latest:
            self.call_from_thread(
                setattr, self, "sub_title",
                f"{gurus} gurus | {holdings:,} holdings | Latest: Q{_qlabel(latest)}"
            )

    # ── Settings ─────────────────────────────────────────────────────

    def action_settings(self) -> None:
        from smart_money.config import get_sec_identity
        current = get_sec_identity() or "(not set)"
        self.push_screen(
            InputModal(f"SEC EDGAR Email (current: {current})", "you@example.com"),
            self._save_sec_email,
        )

    def _save_sec_email(self, email: str) -> None:
        if not email:
            return
        if "@" not in email:
            self.notify("Invalid email address", severity="error")
            return
        from smart_money.config import set_sec_identity
        set_sec_identity(email)
        self.notify(f"SEC identity set to {email}", severity="information")

    def _check_sec_identity(self) -> None:
        """Prompt for SEC email on first run if not configured."""
        from smart_money.config import get_sec_identity
        if not get_sec_identity():
            self.push_screen(
                InputModal(
                    "Welcome! SEC EDGAR requires an email for access.\nEnter your email:",
                    "you@example.com",
                ),
                self._save_sec_email,
            )

    # ── Navigation ───────────────────────────────────────────────────

    def _rebuild_view(self, view_name: str, params=None) -> None:
        """Rebuild a view by name (used for back navigation)."""
        if view_name == "gurus":
            self.action_gurus()
        elif view_name == "top":
            self.action_top()
        elif view_name == "query" and params:
            self._run_query(params)
        elif view_name == "portfolio" and params:
            self._run_portfolio(params)

    def _restore_cursor(self, row: int) -> None:
        """Move the DataTable cursor to the given row."""
        try:
            table = self.query_one(DataTable)
            table.move_cursor(row=row)
        except Exception:
            pass

    def action_go_home(self) -> None:
        if self._view == "home":
            return
        if self._history:
            view_name, cursor_row, params = self._history.pop()
            self._rebuild_view(view_name, params)
            self.set_timer(0.1, lambda: self._restore_cursor(cursor_row))
        else:
            self._go_home()

    def action_force_home(self) -> None:
        self._history.clear()
        self._go_home()


def main():
    SmartMoneyApp().run()


if __name__ == "__main__":
    main()
