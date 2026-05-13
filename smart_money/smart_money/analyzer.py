from smart_money.db import get_db


def get_holders_of_ticker(ticker, quarter=None):
    with get_db() as conn:
        if quarter:
            target_quarter = quarter
        else:
            row = conn.execute(
                "SELECT MAX(report_period) as q FROM holdings WHERE ticker = ?",
                (ticker.upper(),)
            ).fetchone()
            if not row or not row["q"]:
                return None, None
            target_quarter = row["q"]

        # Get previous quarter
        prev_quarter = conn.execute("""
            SELECT MAX(report_period) as q FROM holdings
            WHERE ticker = ? AND report_period < ?
        """, (ticker.upper(), target_quarter)).fetchone()
        prev_q = prev_quarter["q"] if prev_quarter else None

        # Current quarter holders
        holders = conn.execute("""
            SELECT
                g.name, g.firm,
                h.shares, h.value_usd, h.portfolio_weight,
                h.report_period,
                hp.shares as prev_shares,
                hp.value_usd as prev_value,
                hp.portfolio_weight as prev_weight
            FROM holdings h
            JOIN gurus g ON h.guru_id = g.id
            LEFT JOIN holdings hp ON hp.guru_id = h.guru_id
                AND hp.cusip = h.cusip
                AND hp.report_period = ?
                AND hp.put_call = h.put_call
            WHERE h.ticker = ? AND h.report_period = ?
            ORDER BY h.portfolio_weight DESC
        """, (prev_q, ticker.upper(), target_quarter)).fetchall()

        # Find exited positions (were in prev quarter, not in current)
        exited = []
        if prev_q:
            exited = conn.execute("""
                SELECT
                    g.name, g.firm,
                    hp.shares as prev_shares,
                    hp.value_usd as prev_value,
                    hp.portfolio_weight as prev_weight
                FROM holdings hp
                JOIN gurus g ON hp.guru_id = g.id
                LEFT JOIN holdings h ON h.guru_id = hp.guru_id
                    AND h.cusip = hp.cusip
                    AND h.report_period = ?
                    AND COALESCE(h.put_call, '') = COALESCE(hp.put_call, '')
                WHERE hp.ticker = ? AND hp.report_period = ?
                    AND h.id IS NULL
                ORDER BY hp.portfolio_weight DESC
            """, (target_quarter, ticker.upper(), prev_q)).fetchall()

    # Build result list
    results = []
    for h in holders:
        prev_shares = h["prev_shares"]
        curr_shares = h["shares"]

        curr_weight = h["portfolio_weight"] or 0
        prev_weight = h["prev_weight"] or 0

        weight_change = curr_weight - prev_weight if prev_shares is not None else None

        if prev_shares is None:
            status = "New"
        elif weight_change and abs(weight_change) >= 0.005:
            status = "Increased" if weight_change > 0 else "Decreased"
        elif curr_shares != prev_shares:
            status = "Increased" if curr_shares > prev_shares else "Decreased"
        else:
            status = "Unchanged"

        results.append({
            "name": h["name"],
            "firm": h["firm"],
            "shares": curr_shares,
            "value_usd": h["value_usd"],
            "weight": curr_weight,
            "weight_change": weight_change,
            "status": status,
        })

    for e in exited:
        prev_weight = e["prev_weight"] or 0
        results.append({
            "name": e["name"],
            "firm": e["firm"],
            "shares": 0,
            "value_usd": 0,
            "weight": 0,
            "weight_change": -prev_weight,
            "status": "Exited",
        })

    return results, target_quarter


def get_guru_portfolio(guru_name, quarter=None):
    with get_db() as conn:
        guru = conn.execute(
            "SELECT id, name, firm FROM gurus WHERE name LIKE ?",
            (f"%{guru_name}%",)
        ).fetchone()

        if not guru:
            return None, None, None

        if quarter:
            target_quarter = quarter
        else:
            row = conn.execute(
                "SELECT MAX(report_period) as q FROM holdings WHERE guru_id = ?",
                (guru["id"],)
            ).fetchone()
            if not row or not row["q"]:
                return guru, None, None
            target_quarter = row["q"]

        prev_quarter = conn.execute("""
            SELECT MAX(report_period) as q FROM holdings
            WHERE guru_id = ? AND report_period < ?
        """, (guru["id"], target_quarter)).fetchone()
        prev_q = prev_quarter["q"] if prev_quarter else None

        holdings = conn.execute("""
            SELECT
                h.ticker, h.issuer, h.cusip,
                h.shares, h.value_usd, h.portfolio_weight,
                hp.shares as prev_shares,
                hp.portfolio_weight as prev_weight
            FROM holdings h
            LEFT JOIN holdings hp ON hp.guru_id = h.guru_id
                AND hp.cusip = h.cusip
                AND hp.report_period = ?
                AND hp.put_call = h.put_call
            WHERE h.guru_id = ? AND h.report_period = ?
            ORDER BY h.portfolio_weight DESC
        """, (prev_q, guru["id"], target_quarter)).fetchall()

        results = []
        for h in holdings:
            prev_shares = h["prev_shares"]
            curr_shares = h["shares"]

            curr_weight = h["portfolio_weight"] or 0
            prev_weight = h["prev_weight"] or 0
            wc = curr_weight - prev_weight if prev_shares is not None else None

            if prev_shares is None:
                status = "New"
            elif wc and abs(wc) >= 0.005:
                status = "Increased" if wc > 0 else "Decreased"
            elif curr_shares != prev_shares:
                status = "Increased" if curr_shares > prev_shares else "Decreased"
            else:
                status = "Unchanged"

            results.append({
                "ticker": h["ticker"] or h["cusip"],
                "issuer": h["issuer"],
                "shares": curr_shares,
                "value_usd": h["value_usd"],
                "weight": h["portfolio_weight"],
                "status": status,
            })

    return guru, target_quarter, results


def get_top_held(quarter=None, limit=20):
    with get_db() as conn:
        if not quarter:
            row = conn.execute("SELECT MAX(report_period) as q FROM holdings").fetchone()
            if not row or not row["q"]:
                return None, None
            quarter = row["q"]

        results = conn.execute("""
            SELECT
                COALESCE(h.ticker, h.cusip) as ticker,
                h.issuer,
                COUNT(DISTINCT h.guru_id) as num_gurus,
                SUM(h.value_usd) as total_value,
                AVG(h.portfolio_weight) as avg_weight,
                MAX(h.portfolio_weight) as max_weight
            FROM holdings h
            WHERE h.report_period = ?
            GROUP BY COALESCE(h.ticker, h.cusip)
            ORDER BY num_gurus DESC, avg_weight DESC
            LIMIT ?
        """, (quarter, limit)).fetchall()

    return [dict(r) for r in results], quarter
