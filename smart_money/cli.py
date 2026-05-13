#!/usr/bin/env python3
"""Smart Money Tracker — track guru institutional holdings from SEC 13F filings."""

import argparse
import sys


def cmd_init(args):
    from smart_money.db import init_db
    from smart_money.gurus import seed_gurus_to_db, resolve_ciks
    from smart_money.fetcher import fetch_all_gurus
    from smart_money.cusip_mapper import resolve_unmapped_tickers, apply_cached_tickers

    print("=== Initializing Smart Money Tracker ===\n")

    # Step 1: Create database
    print("Step 1: Creating database...")
    init_db()

    # Step 2: Seed guru list
    print("\nStep 2: Seeding guru list...")
    seed_gurus_to_db()

    # Step 3: Resolve CIKs
    print("\nStep 3: Resolving SEC CIK numbers for each guru...")
    print("(This searches SEC EDGAR for each firm — may take a few minutes)\n")
    resolve_ciks()

    # Step 4: Fetch 13F filings
    quarters = args.quarters if hasattr(args, "quarters") else 4
    print(f"\nStep 4: Fetching last {quarters} quarter(s) of 13F filings...")
    fetch_all_gurus(num_quarters=quarters)

    # Step 5: Resolve CUSIP-to-ticker mappings
    print("\nStep 5: Resolving CUSIP-to-ticker mappings...")
    apply_cached_tickers()
    resolve_unmapped_tickers()

    print("\n=== Initialization complete! ===")
    print("Try: python cli.py query AAPL")


def cmd_update(args):
    from smart_money.fetcher import fetch_all_gurus
    from smart_money.cusip_mapper import resolve_unmapped_tickers, apply_cached_tickers

    print("=== Updating holdings (latest quarter) ===\n")
    fetch_all_gurus(num_quarters=1)

    print("\nResolving new CUSIP-to-ticker mappings...")
    apply_cached_tickers()
    resolve_unmapped_tickers()

    print("\n=== Update complete! ===")


def cmd_query(args):
    from smart_money.analyzer import get_holders_of_ticker
    from smart_money.display import display_ticker_holders

    results, quarter = get_holders_of_ticker(args.ticker, quarter=args.quarter)
    if results is None:
        print(f"No data found for {args.ticker.upper()}")
        print("Make sure you've run 'python cli.py init' first.")
        sys.exit(1)

    display_ticker_holders(results, args.ticker, quarter)


def cmd_portfolio(args):
    from smart_money.analyzer import get_guru_portfolio
    from smart_money.display import display_portfolio

    guru, quarter, holdings = get_guru_portfolio(args.name, quarter=args.quarter)
    if guru is None:
        print(f"No guru found matching '{args.name}'")
        sys.exit(1)
    if holdings is None:
        print(f"No holdings data found for {guru['name']}")
        sys.exit(1)

    display_portfolio(guru, quarter, holdings)


def cmd_top(args):
    from smart_money.analyzer import get_top_held
    from smart_money.display import display_top_held

    results, quarter = get_top_held(quarter=args.quarter, limit=args.limit)
    if results is None:
        print("No holdings data found. Run 'python cli.py init' first.")
        sys.exit(1)

    display_top_held(results, quarter)


def cmd_gurus(args):
    from smart_money.gurus import list_gurus
    from smart_money.display import display_gurus

    gurus = list_gurus(show_all=args.all)
    display_gurus(gurus, show_all=args.all)


def main():
    parser = argparse.ArgumentParser(
        description="Smart Money Tracker — track guru holdings from SEC 13F filings"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # init
    p_init = subparsers.add_parser("init", help="Initialize DB, seed gurus, fetch filings")
    p_init.add_argument("--quarters", type=int, default=4,
                        help="Number of quarters to fetch (default: 4)")
    p_init.set_defaults(func=cmd_init)

    # update
    p_update = subparsers.add_parser("update", help="Fetch latest quarter for all gurus")
    p_update.set_defaults(func=cmd_update)

    # query
    p_query = subparsers.add_parser("query", help="Search for a ticker across all guru holdings")
    p_query.add_argument("ticker", help="Stock ticker to search (e.g., AAPL)")
    p_query.add_argument("--quarter", help="Specific quarter (e.g., 2024-12-31)")
    p_query.set_defaults(func=cmd_query)

    # portfolio
    p_portfolio = subparsers.add_parser("portfolio", help="View a guru's full portfolio")
    p_portfolio.add_argument("name", help="Guru name (partial match, e.g., 'Buffett')")
    p_portfolio.add_argument("--quarter", help="Specific quarter (e.g., 2024-12-31)")
    p_portfolio.set_defaults(func=cmd_portfolio)

    # top
    p_top = subparsers.add_parser("top", help="Top held stocks across all gurus")
    p_top.add_argument("--quarter", help="Specific quarter (e.g., 2024-12-31)")
    p_top.add_argument("--limit", type=int, default=20, help="Number of results (default: 20)")
    p_top.set_defaults(func=cmd_top)

    # gurus
    p_gurus = subparsers.add_parser("gurus", help="List tracked gurus")
    p_gurus.add_argument("--all", action="store_true", help="Show all gurus including inactive")
    p_gurus.set_defaults(func=cmd_gurus)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
