import time
from smart_money.config import FETCH_DELAY, require_sec_identity
from smart_money.db import get_db, store_holdings


def fetch_all_gurus(num_quarters=1, min_history=4, progress_callback=None):
    """Fetch 13F filings for all active gurus.

    Args:
        num_quarters: Number of latest quarters to fetch on every run.
        min_history: Backfill target — gurus with fewer than this many quarters
            stored will fetch extra historical filings to reach this baseline.
            This makes QoQ change detection work for newly-added gurus.
        progress_callback: Optional callable(current, total, guru_name, status)
            where status is 'fetching', 'ok', 'skipped', or 'error'.
    """
    from edgar import set_identity
    set_identity(require_sec_identity())

    with get_db() as conn:
        gurus = conn.execute(
            "SELECT id, name, firm, cik FROM gurus WHERE active = 1 AND cik IS NOT NULL"
        ).fetchall()
        existing_counts = {
            r["guru_id"]: r["c"]
            for r in conn.execute(
                "SELECT guru_id, COUNT(DISTINCT report_period) as c "
                "FROM holdings GROUP BY guru_id"
            ).fetchall()
        }

    if not gurus:
        print("No active gurus with CIKs found. Run 'init' first.")
        return

    total = len(gurus)
    success = 0
    failed = []

    print(f"Fetching 13F filings for {total} gurus "
          f"(latest {num_quarters}, backfill to {min_history})...\n")

    for i, guru in enumerate(gurus, 1):
        guru_id = guru["id"]
        name = guru["name"]
        cik = guru["cik"]

        existing = existing_counts.get(guru_id, 0)
        to_fetch = max(num_quarters, min_history - existing) if existing < min_history else num_quarters

        print(f"[{i}/{total}] {name} (CIK: {cik})...", end=" ", flush=True)
        if progress_callback:
            progress_callback(i, total, name, "fetching")

        try:
            filings = _fetch_holdings_for_cik(cik, to_fetch)
            if not filings:
                print("no 13F filings found")
                failed.append((name, "no filings"))
                if progress_callback:
                    progress_callback(i, total, name, "skipped")
                continue

            stored = 0
            skipped = 0
            for filing_data in filings:
                with get_db() as conn:
                    was_new = store_holdings(conn, guru_id, filing_data)
                    if was_new:
                        stored += 1
                    else:
                        skipped += 1

            with get_db() as conn:
                conn.execute(
                    "UPDATE gurus SET last_updated = datetime('now') WHERE id = ?",
                    (guru_id,)
                )

            print(f"{stored} new, {skipped} skipped")
            success += 1
            if progress_callback:
                progress_callback(i, total, name, "ok")

        except Exception as e:
            print(f"ERROR: {e}")
            failed.append((name, str(e)))
            if progress_callback:
                progress_callback(i, total, name, "error")

        time.sleep(FETCH_DELAY)

    print(f"\nDone: {success}/{total} gurus processed successfully")
    if failed:
        print(f"Failed ({len(failed)}):")
        for name, reason in failed:
            print(f"  - {name}: {reason}")


def _fetch_holdings_for_cik(cik, num_quarters):
    from edgar import Company

    company = Company(cik)
    filings_set = company.get_filings(form="13F-HR")

    if filings_set is None or len(filings_set) == 0:
        return []

    recent = filings_set.latest(num_quarters)
    if recent is None:
        return []
    if not hasattr(recent, "__iter__"):
        recent = [recent]

    results = []
    for filing in recent:
        try:
            obj = filing.obj()

            report_period = str(obj.report_period or filing.report_date or "")
            filing_date = str(filing.filing_date or "")
            accession = str(filing.accession_number or "")

            # edgartools infotable is a pandas DataFrame with known columns:
            # Issuer, Class, Cusip, Value, PutCall, SharesPrnAmount, Type, Ticker
            infotable = obj.infotable
            if infotable is None or (hasattr(infotable, "empty") and infotable.empty):
                continue

            total_value = obj.total_value or 0
            holdings_data = []

            for _, row in infotable.iterrows():
                cusip = row.get("Cusip")
                if not cusip or str(cusip) == "nan":
                    continue

                value = int(float(row.get("Value") or 0))
                shares = int(float(row.get("SharesPrnAmount") or 0))
                ticker = row.get("Ticker")
                if ticker and str(ticker) == "nan":
                    ticker = None

                put_call = row.get("PutCall")
                if put_call and str(put_call) == "nan":
                    put_call = None

                holdings_data.append({
                    "cusip": str(cusip).strip(),
                    "issuer": str(row.get("Issuer") or ""),
                    "ticker": str(ticker) if ticker else None,
                    "class_title": str(row.get("Class") or ""),
                    "value_usd": value,
                    "shares": shares,
                    "share_type": str(row.get("Type") or "SH"),
                    "put_call": str(put_call) if put_call else "",
                })

            # Aggregate duplicate CUSIPs (e.g., Berkshire reports by sub-manager)
            holdings_data = _aggregate_holdings(holdings_data)

            if not holdings_data:
                continue

            results.append({
                "report_period": report_period,
                "filing_date": filing_date,
                "accession_number": accession,
                "total_value": total_value,
                "holdings": holdings_data,
            })
        except Exception as e:
            print(f"\n    Warning: could not parse filing: {e}")
            continue

    return results


def _aggregate_holdings(holdings):
    """Combine duplicate CUSIP+put_call entries by summing shares and value."""
    aggregated = {}
    for h in holdings:
        key = (h["cusip"], h["put_call"])
        if key in aggregated:
            aggregated[key]["shares"] += h["shares"]
            aggregated[key]["value_usd"] += h["value_usd"]
        else:
            aggregated[key] = dict(h)
    return list(aggregated.values())
