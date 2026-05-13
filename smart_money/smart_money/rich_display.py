"""Rich-powered display for the Smart Money TUI."""

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.columns import Columns

console = Console()


def format_value(value_usd):
    if value_usd is None or value_usd == 0:
        return "--"
    if value_usd >= 1_000_000_000:
        return f"${value_usd / 1_000_000_000:.2f}B"
    if value_usd >= 1_000_000:
        return f"${value_usd / 1_000_000:.1f}M"
    if value_usd >= 1_000:
        return f"${value_usd / 1_000:.0f}K"
    return f"${value_usd}"


def format_shares(shares):
    if shares is None or shares == 0:
        return "--"
    if shares >= 1_000_000:
        return f"{shares / 1_000_000:.2f}M"
    if shares >= 1_000:
        return f"{shares / 1_000:.1f}K"
    return str(shares)


def format_weight(weight):
    if weight is None:
        return "--"
    return f"{weight:.2f}%"


def _change_style(status):
    """Return a rich style string for a QoQ status."""
    if status in ("New",):
        return "bold green"
    if status == "Increased":
        return "green"
    if status == "Decreased":
        return "red"
    if status == "Exited":
        return "bold red"
    return "dim"


def format_change(status, weight_change):
    if status == "New":
        return Text("NEW", style="bold green")
    if status == "Exited":
        return Text("EXITED", style="bold red")
    if status == "Unchanged":
        return Text("Unchanged", style="dim")
    if weight_change is not None:
        sign = "+" if weight_change > 0 else ""
        label = f"{status} ({sign}{weight_change:.2f}pp)"
        style = "green" if weight_change > 0 else "red"
        return Text(label, style=style)
    return Text(status)


def display_ticker_holders(results, ticker, quarter):
    if not results:
        console.print(f"\n[dim]No guru holdings found for {ticker.upper()}[/dim]")
        return

    table = Table(
        title=f"  {ticker.upper()}  --  Q{_quarter_label(quarter)}",
        title_style="bold cyan",
        border_style="bright_black",
        header_style="bold white",
        show_lines=False,
        padding=(0, 1),
        expand=True,
    )

    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Guru", style="bold", min_width=18)
    table.add_column("Firm", style="dim", min_width=18)
    table.add_column("Weight", justify="right", min_width=8)
    table.add_column("Shares", justify="right", min_width=10)
    table.add_column("Value", justify="right", min_width=10)
    table.add_column("QoQ Change", min_width=20)

    for i, r in enumerate(results, 1):
        weight_text = Text(format_weight(r["weight"]))
        if r["weight"] and r["weight"] >= 5:
            weight_text.stylize("bold yellow")
        elif r["weight"] and r["weight"] >= 2:
            weight_text.stylize("white")

        table.add_row(
            str(i),
            r["name"],
            r["firm"],
            weight_text,
            format_shares(r["shares"]),
            format_value(r["value_usd"]),
            format_change(r["status"], r.get("weight_change")),
        )

    console.print()
    console.print(table)

    # Summary bar
    active = [r for r in results if r["status"] != "Exited"]
    increased = sum(1 for r in results if r["status"] == "Increased")
    decreased = sum(1 for r in results if r["status"] == "Decreased")
    new = sum(1 for r in results if r["status"] == "New")
    exited = sum(1 for r in results if r["status"] == "Exited")
    unchanged = sum(1 for r in results if r["status"] == "Unchanged")
    avg_weight = (sum(r["weight"] for r in active if r["weight"])
                  / len(active)) if active else 0

    summary = Text()
    summary.append(f"  {len(active)} guru(s)", style="bold")
    summary.append(f"  Avg weight: {avg_weight:.2f}%", style="cyan")
    if new:
        summary.append(f"  {new} new", style="bold green")
    if increased:
        summary.append(f"  {increased} increased", style="green")
    if unchanged:
        summary.append(f"  {unchanged} unchanged", style="dim")
    if decreased:
        summary.append(f"  {decreased} decreased", style="red")
    if exited:
        summary.append(f"  {exited} exited", style="bold red")

    console.print(summary)
    console.print()


def display_portfolio(guru, quarter, holdings):
    if not holdings:
        console.print(f"\n[dim]No holdings found for {guru['name']}[/dim]")
        return

    table = Table(
        title=f"  {guru['name']}  ({guru['firm']})  --  Q{_quarter_label(quarter)}",
        title_style="bold cyan",
        border_style="bright_black",
        header_style="bold white",
        show_lines=False,
        padding=(0, 1),
        expand=True,
    )

    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Ticker", style="bold cyan", min_width=8)
    table.add_column("Issuer", min_width=20)
    table.add_column("Weight", justify="right", min_width=8)
    table.add_column("Shares", justify="right", min_width=10)
    table.add_column("Value", justify="right", min_width=10)
    table.add_column("QoQ", min_width=12)

    for i, h in enumerate(holdings, 1):
        weight_text = Text(format_weight(h["weight"]))
        if h["weight"] and h["weight"] >= 5:
            weight_text.stylize("bold yellow")
        elif h["weight"] and h["weight"] >= 2:
            weight_text.stylize("white")

        status_text = Text(h["status"], style=_change_style(h["status"]))

        table.add_row(
            str(i),
            h["ticker"] or "???",
            h["issuer"][:35],
            weight_text,
            format_shares(h["shares"]),
            format_value(h["value_usd"]),
            status_text,
        )

    console.print()
    console.print(table)
    console.print(f"  [dim]{len(holdings)} holdings[/dim]\n")


def display_top_held(results, quarter):
    if not results:
        console.print("\n[dim]No holdings data found[/dim]")
        return

    table = Table(
        title=f"  Top Held Stocks  --  Q{_quarter_label(quarter)}",
        title_style="bold cyan",
        border_style="bright_black",
        header_style="bold white",
        show_lines=False,
        padding=(0, 1),
        expand=True,
    )

    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Ticker", style="bold cyan", min_width=8)
    table.add_column("Issuer", min_width=20)
    table.add_column("# Gurus", justify="right", style="bold", min_width=8)
    table.add_column("Avg Wt%", justify="right", min_width=8)
    table.add_column("Max Wt%", justify="right", min_width=8)
    table.add_column("Total Value", justify="right", min_width=12)

    for i, r in enumerate(results, 1):
        guru_count = str(r["num_gurus"])
        guru_style = "bold yellow" if r["num_gurus"] >= 10 else "bold"

        table.add_row(
            str(i),
            r["ticker"] or "???",
            (r["issuer"] or "")[:35],
            Text(guru_count, style=guru_style),
            format_weight(r["avg_weight"]),
            format_weight(r["max_weight"]),
            format_value(r["total_value"]),
        )

    console.print()
    console.print(table)
    console.print()


def display_gurus(gurus, show_all=False):
    if not gurus:
        console.print("\n[dim]No gurus found[/dim]")
        return

    label = "All" if show_all else "Active"

    table = Table(
        title=f"  {label} Gurus  ({len(gurus)})",
        title_style="bold cyan",
        border_style="bright_black",
        header_style="bold white",
        show_lines=False,
        padding=(0, 1),
        expand=True,
    )

    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Name", style="bold", min_width=20)
    table.add_column("Firm", min_width=20)
    table.add_column("CIK", style="dim", min_width=12)
    table.add_column("Status", min_width=10)
    table.add_column("Last Updated", style="dim", min_width=12)

    for i, g in enumerate(gurus, 1):
        if g["active"]:
            status = Text("Active", style="green")
        else:
            status = Text(g["notes"] or "Inactive", style="dim red")

        table.add_row(
            str(i),
            g["name"],
            g["firm"],
            g["cik"] or "--",
            status,
            g["last_updated"] or "--",
        )

    console.print()
    console.print(table)
    console.print()


def display_db_stats():
    """Show database statistics for the welcome screen."""
    from smart_money.db import get_db

    try:
        with get_db() as conn:
            gurus = conn.execute("SELECT COUNT(*) as c FROM gurus WHERE active = 1").fetchone()["c"]
            holdings = conn.execute("SELECT COUNT(*) as c FROM holdings").fetchone()["c"]
            quarters_row = conn.execute(
                "SELECT COUNT(DISTINCT report_period) as c FROM holdings"
            ).fetchone()
            quarters = quarters_row["c"]
            latest_row = conn.execute("SELECT MAX(report_period) as q FROM holdings").fetchone()
            latest = latest_row["q"] if latest_row else None

        return {
            "gurus": gurus,
            "holdings": holdings,
            "quarters": quarters,
            "latest_quarter": latest,
        }
    except Exception:
        return None


def _quarter_label(quarter_str):
    """Convert '2024-12-31' to '4 2024' for display."""
    if not quarter_str:
        return "?"
    try:
        parts = quarter_str.split("-")
        year = parts[0]
        month = int(parts[1])
        q = {3: 1, 6: 2, 9: 3, 12: 4}.get(month, "?")
        return f"{q} {year}"
    except (IndexError, ValueError):
        return quarter_str
