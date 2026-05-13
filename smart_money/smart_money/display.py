from tabulate import tabulate


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


def format_change(status, weight_change):
    if status == "New":
        return "New Position"
    if status == "Exited":
        return "Exited"
    if status == "Unchanged":
        return "Unchanged"
    if weight_change is not None:
        sign = "+" if weight_change > 0 else ""
        return f"{status} ({sign}{weight_change:.2f}pp)"
    return status


def display_ticker_holders(results, ticker, quarter):
    if not results:
        print(f"\nNo guru holdings found for {ticker.upper()}")
        return

    print(f"\n{ticker.upper()} — {quarter}")
    print("=" * 100)

    table_data = []
    for r in results:
        table_data.append([
            r["name"],
            r["firm"],
            format_weight(r["weight"]),
            format_shares(r["shares"]),
            format_value(r["value_usd"]),
            format_change(r["status"], r.get("weight_change")),
        ])

    headers = ["Guru", "Firm", "Weight %", "Shares", "Value", "QoQ Change"]
    print(tabulate(table_data, headers=headers, tablefmt="simple"))

    # Summary
    active = [r for r in results if r["status"] != "Exited"]
    increased = sum(1 for r in results if r["status"] == "Increased")
    decreased = sum(1 for r in results if r["status"] == "Decreased")
    new = sum(1 for r in results if r["status"] == "New")
    exited = sum(1 for r in results if r["status"] == "Exited")
    unchanged = sum(1 for r in results if r["status"] == "Unchanged")

    avg_weight = (sum(r["weight"] for r in active if r["weight"])
                  / len(active)) if active else 0

    parts = []
    parts.append(f"{len(active)} guru(s) hold {ticker.upper()}")
    parts.append(f"Avg weight: {avg_weight:.2f}%")
    changes = []
    if new:
        changes.append(f"{new} new")
    if increased:
        changes.append(f"{increased} increased")
    if unchanged:
        changes.append(f"{unchanged} unchanged")
    if decreased:
        changes.append(f"{decreased} decreased")
    if exited:
        changes.append(f"{exited} exited")
    if changes:
        parts.append(", ".join(changes))

    print(f"\nSummary: {' | '.join(parts)}")


def display_portfolio(guru, quarter, holdings):
    if not holdings:
        print(f"\nNo holdings found for {guru['name']}")
        return

    print(f"\n{guru['name']} ({guru['firm']}) — {quarter}")
    print("=" * 100)

    table_data = []
    for h in holdings:
        table_data.append([
            h["ticker"],
            h["issuer"][:30],
            format_weight(h["weight"]),
            format_shares(h["shares"]),
            format_value(h["value_usd"]),
            h["status"],
        ])

    headers = ["Ticker", "Issuer", "Weight %", "Shares", "Value", "QoQ"]
    print(tabulate(table_data, headers=headers, tablefmt="simple"))
    print(f"\n{len(holdings)} holdings")


def display_top_held(results, quarter):
    if not results:
        print("\nNo holdings data found")
        return

    print(f"\nTop Held Stocks Across All Gurus — {quarter}")
    print("=" * 90)

    table_data = []
    for i, r in enumerate(results, 1):
        table_data.append([
            i,
            r["ticker"],
            r["issuer"][:30],
            r["num_gurus"],
            format_weight(r["avg_weight"]),
            format_weight(r["max_weight"]),
            format_value(r["total_value"]),
        ])

    headers = ["#", "Ticker", "Issuer", "# Gurus", "Avg Wt%", "Max Wt%", "Total Value"]
    print(tabulate(table_data, headers=headers, tablefmt="simple"))


def display_gurus(gurus, show_all=False):
    if not gurus:
        print("\nNo gurus found")
        return

    label = "All" if show_all else "Active"
    print(f"\n{label} Gurus ({len(gurus)})")
    print("=" * 80)

    table_data = []
    for g in gurus:
        status = "Active" if g["active"] else (g["notes"] or "Inactive")
        table_data.append([
            g["name"],
            g["firm"],
            g["cik"] or "--",
            status,
            g["last_updated"] or "--",
        ])

    headers = ["Name", "Firm", "CIK", "Status", "Last Updated"]
    print(tabulate(table_data, headers=headers, tablefmt="simple"))
