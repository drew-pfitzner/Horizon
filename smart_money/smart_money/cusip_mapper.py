import requests
import time
from smart_money.config import OPENFIGI_URL, OPENFIGI_BATCH_SIZE
from smart_money.db import get_db


def resolve_unmapped_tickers():
    with get_db() as conn:
        # Find holdings with no ticker that also aren't in the cache
        rows = conn.execute("""
            SELECT DISTINCT h.cusip, h.issuer
            FROM holdings h
            LEFT JOIN cusip_ticker_map m ON h.cusip = m.cusip
            WHERE h.ticker IS NULL AND m.cusip IS NULL
        """).fetchall()

    if not rows:
        print("All CUSIPs already mapped.")
        return

    print(f"Resolving tickers for {len(rows)} unmapped CUSIPs...")

    # Batch them for OpenFIGI
    cusips = [(r["cusip"], r["issuer"]) for r in rows]
    mapped = _batch_resolve_openfigi(cusips)

    # Store mappings and update holdings
    with get_db() as conn:
        for cusip, ticker, issuer in mapped:
            conn.execute("""
                INSERT OR REPLACE INTO cusip_ticker_map (cusip, ticker, issuer_name, source)
                VALUES (?, ?, ?, 'openfigi')
            """, (cusip, ticker, issuer))

            if ticker:
                conn.execute(
                    "UPDATE holdings SET ticker = ? WHERE cusip = ? AND ticker IS NULL",
                    (ticker, cusip)
                )

    resolved = sum(1 for _, t, _ in mapped if t)
    print(f"Resolved {resolved}/{len(rows)} CUSIPs to tickers")


def _batch_resolve_openfigi(cusips):
    results = []

    for i in range(0, len(cusips), OPENFIGI_BATCH_SIZE):
        batch = cusips[i:i + OPENFIGI_BATCH_SIZE]
        payload = [{"idType": "ID_CUSIP", "idValue": c.upper()} for c, _ in batch]

        try:
            resp = requests.post(
                OPENFIGI_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )

            if resp.status_code == 429:
                print("  Rate limited by OpenFIGI, waiting 60s...")
                time.sleep(60)
                resp = requests.post(
                    OPENFIGI_URL,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=30,
                )

            if resp.status_code != 200:
                print(f"  OpenFIGI error: {resp.status_code}")
                for cusip, issuer in batch:
                    results.append((cusip, None, issuer))
                continue

            data = resp.json()
            for j, item in enumerate(data):
                cusip = batch[j][0]
                issuer = batch[j][1]

                if "data" in item and item["data"]:
                    ticker = item["data"][0].get("ticker")
                    results.append((cusip, ticker, issuer))
                else:
                    results.append((cusip, None, issuer))

        except Exception as e:
            print(f"  OpenFIGI batch error: {e}")
            for cusip, issuer in batch:
                results.append((cusip, None, issuer))

        # Rate limit: 25 requests/min without API key
        if i + OPENFIGI_BATCH_SIZE < len(cusips):
            time.sleep(3)

    return results


def apply_cached_tickers():
    with get_db() as conn:
        updated = conn.execute("""
            UPDATE holdings
            SET ticker = (
                SELECT m.ticker FROM cusip_ticker_map m
                WHERE m.cusip = holdings.cusip AND m.ticker IS NOT NULL
            )
            WHERE ticker IS NULL
            AND cusip IN (SELECT cusip FROM cusip_ticker_map WHERE ticker IS NOT NULL)
        """).rowcount
    if updated:
        print(f"Applied {updated} cached ticker mappings")
