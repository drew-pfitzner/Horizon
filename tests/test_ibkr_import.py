"""End-to-end tests for the IBKR CSV importer.

Run from the Horizon directory:

    venv/bin/python -m unittest discover -s tests -v

Each test gets its own temp horizon.db, so HORIZON_DB_PATH has to be set before
anything imports config. That's why the env var is poked in at module import
time rather than in setUp.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP = tempfile.mkdtemp(prefix="horizon-test-")
os.environ["HORIZON_DB_PATH"] = str(Path(_TMP) / "horizon.db")

import db as dbmod                    # noqa: E402
import ibkr_import as imp             # noqa: E402
from app import create_app            # noqa: E402


SAMPLE = """Statement,Header,Field Name,Field Value
Statement,Data,Title,Transaction History
Statement,Data,Period,"August 14, 2026 - September 14, 2026"
Summary,Header,Field Name,Field Value
Summary,Data,Base Currency,AUD
Transaction History,Header,Date,Account,Description,Transaction Type,Symbol,Quantity,Price,Price Currency,Gross Amount ,Commission,Net Amount
Transaction History,Data,2026-09-14,U***56746,DECKERS OUTDOOR CORP,Buy,DECK,0.8276,80.585,USD,-93.40,-0.9340936745658001,-94.34
Transaction History,Data,2026-09-14,U***56746,DECKERS OUTDOOR CORP,Buy,DECK,0.0038,80.95,USD,-0.43,-0.0043084010666,-0.43
Transaction History,Data,2026-09-14,U***56746,SHARKNINJA INC,Buy,SN,0.4171,160.6,USD,-93.82,-0.9382113097106001,-94.75
Transaction History,Data,2026-09-14,U***56746,Net Amount in Base from Forex Trade: -93.11 AUD.USD,Forex Trade Component,AUD.USD,-93.11,0.71089,USD,-0.40,-,-0.40
Transaction History,Data,2026-09-14,U***56746,FX Translations P&L,Adjustment,-,-,-,-,-3.35,-,-3.35
Transaction History,Data,2026-09-03,U***56746,ARGAN INC,Buy,AGX,0.1586,422.28,USD,-93.01,-0.9301301289728001,-93.94
Transaction History,Data,2026-09-01,U***56746,TJX COMPANIES INC,Buy,TJX,0.499,134.2074,USD,-93.73,-0.9373071136308,-94.66
Transaction History,Data,2026-09-01,U***56746,TJX COMPANIES INC,Buy,TJX,2.0E-4,134.25,USD,-0.037,-3.7579399959999997E-4,-0.037
Transaction History,Data,2026-08-28,U***56746,ACCENTURE PLC-CL A,Sell,ACN,-0.0048,189.43,USD,1.26,-0.013991482548400002,1.25
Transaction History,Data,2026-08-24,U***56746,NETFLIX INC,Sell,NFLX,-0.5205,80.25,USD,58.41,-0.5855445529164001,57.83
Transaction History,Data,2026-08-17,U***56746,ACCENTURE PLC-CL A,Buy,ACN,0.0048,174.16,USD,-1.17,-0.0011767282632,-1.17
Transaction History,Data,2026-08-15,U***56746,ACN(IE00B4BNMY34) Cash Dividend USD 1.63 per Share,Dividend,ACN,-,-,-,1.18,-,1.18
"""


def _txn(rows, period=("August 1, 2026", "September 30, 2026")):
    """Build a Transaction History CSV from (date, desc, type, sym, qty, px, comm)."""
    head = [
        "Statement,Header,Field Name,Field Value",
        f'Statement,Data,Period,"{period[0]} - {period[1]}"',
        "Transaction History,Header,Date,Account,Description,Transaction Type,"
        "Symbol,Quantity,Price,Price Currency,Gross Amount ,Commission,Net Amount",
    ]
    for d, desc, typ, sym, qty, px, comm in rows:
        head.append(f"Transaction History,Data,{d},U***56746,{desc},{typ},{sym},"
                    f"{qty},{px},USD,0,{comm},0")
    return "\n".join(head) + "\n"


class ImporterTest(unittest.TestCase):
    def setUp(self):
        path = Path(os.environ["HORIZON_DB_PATH"])
        if path.exists():
            path.unlink()
        for suffix in ("-wal", "-shm"):
            extra = Path(str(path) + suffix)
            if extra.exists():
                extra.unlink()
        dbmod.init_db()
        self.client = create_app().test_client()

    # -- helpers ----------------------------------------------------------

    def preview(self, csv_text, resolutions=None):
        r = self.client.post("/api/trades/import/preview",
                             json={"csv": csv_text, "resolutions": resolutions or {}})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        return r.get_json()["data"]

    def apply(self, csv_text, resolutions=None, accept=None):
        body = {"csv": csv_text, "resolutions": resolutions or {}}
        if accept is not None:
            body["accept"] = accept
        r = self.client.post("/api/trades/import/apply", json=body)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        return r.get_json()["data"]

    def trades(self):
        r = self.client.get("/api/trades")
        return {t["ticker"]: t for t in r.get_json()["data"]}

    def all_trades(self):
        return self.client.get("/api/trades").get_json()["data"]

    def action(self, plan, ticker):
        matches = [a for a in plan["actions"] if a["ticker"] == ticker]
        self.assertTrue(matches, f"no action for {ticker}")
        return matches[0]

    # -- parsing ----------------------------------------------------------

    def test_parses_only_real_trades(self):
        parsed = imp.parse_csv(SAMPLE)
        self.assertEqual(parsed["period"], {"start": "2026-08-14", "end": "2026-09-14"})
        self.assertEqual(parsed["account"], "U***56746")
        self.assertEqual(len(parsed["fills"]), 9)
        self.assertNotIn("AUD.USD", {f["ticker"] for f in parsed["fills"]})
        self.assertIn("Forex Trade Component", parsed["ignored"])
        self.assertEqual(parsed["dividends"][0]["ticker"], "ACN")

    def test_reads_a_flat_flex_query_export(self):
        flex = ("Symbol,TradeDate,Buy/Sell,Quantity,TradePrice,IBCommission,"
                "CurrencyPrimary,TradeID,AssetCategory,Description\n"
                "DECK,20260914,BUY,0.8276,80.585,-0.93,USD,77771,STK,DECKERS OUTDOOR CORP\n"
                "AUD.USD,20260914,SELL,-93.11,0.71089,0,USD,77772,CASH,forex\n")
        parsed = imp.parse_csv(flex)
        self.assertEqual([f["ticker"] for f in parsed["fills"]], ["DECK"])
        self.assertEqual(parsed["fills"][0]["trade_date"], "2026-09-14")
        # A broker trade id becomes the fingerprint, which is the strongest
        # possible dedupe key.
        self.assertEqual(parsed["fills"][0]["fill_key"], "ibkr:tx:77771")

    def test_rejects_a_csv_with_no_trades(self):
        with self.assertRaises(imp.ImportError_):
            imp.parse_csv("Statement,Header,Field Name,Field Value\n")

    # -- first import -----------------------------------------------------

    def test_first_import_creates_positions_and_merges_split_fills(self):
        plan = self.preview(SAMPLE)
        self.assertEqual(plan["fills_new"], 9)
        self.assertEqual(plan["fills_known"], 0)

        deck = self.action(plan, "DECK")
        self.assertEqual(deck["action"], "create")
        self.assertEqual(len(deck["targets"]), 1)
        # Two fills of one order collapse into a single position.
        self.assertAlmostEqual(deck["targets"][0]["derived"]["shares"], 0.8314, places=6)
        self.assertAlmostEqual(deck["targets"][0]["derived"]["entry_price"],
                               (0.8276 * 80.585 + 0.0038 * 80.95) / 0.8314, places=6)

        self.apply(SAMPLE, resolutions={self.action(plan, "NFLX")["key"]: {"mode": "ignore"}})
        rows = self.trades()
        self.assertEqual(set(rows), {"DECK", "SN", "AGX", "TJX", "ACN"})

        # ACN bought and sold inside the window is one closed round trip.
        acn = rows["ACN"]
        self.assertEqual(acn["entry_date"], "2026-08-17")
        self.assertEqual(acn["exit_date"], "2026-08-28")
        self.assertEqual(acn["win_loss"], "WIN")
        self.assertIsNotNone(acn["pl_dollar"])

        # Actual IBKR commission is used, not the 1% estimate.
        self.assertAlmostEqual(rows["SN"]["entry_fee"], 0.938211, places=5)

    def test_reimporting_the_same_file_changes_nothing(self):
        nflx = {self.action(self.preview(SAMPLE), "NFLX")["key"]: {"mode": "ignore"}}
        self.apply(SAMPLE, resolutions=nflx)
        before = self.all_trades()

        plan = self.preview(SAMPLE)
        self.assertEqual(plan["fills_new"], 0)
        self.assertEqual(plan["fills_known"], 9)
        self.assertTrue(all(a["action"] == "skip" for a in plan["actions"]),
                        [a["action"] for a in plan["actions"]])

        result = self.apply(SAMPLE, resolutions=nflx)
        self.assertEqual((result["created"], result["updated"]), (0, 0))
        self.assertEqual(self.all_trades(), before)

    # -- ambiguity --------------------------------------------------------

    def test_sale_with_no_known_entry_asks_rather_than_guesses(self):
        plan = self.preview(SAMPLE)
        nflx = self.action(plan, "NFLX")
        self.assertEqual(nflx["action"], "ambiguous")
        self.assertEqual(nflx["question"], "orphan_sell")
        self.assertIn(nflx["key"], plan["needs_input"])
        self.assertEqual([o["mode"] for o in nflx["options"]], ["entry", "ignore"])

        # Applying it unanswered is refused rather than half-done.
        r = self.client.post("/api/trades/import/apply",
                             json={"csv": SAMPLE, "accept": [nflx["key"]]})
        self.assertEqual(r.status_code, 400)

    def test_answering_the_orphan_sale_logs_the_full_round_trip(self):
        plan = self.preview(SAMPLE)
        key = self.action(plan, "NFLX")["key"]
        res = {key: {"mode": "entry", "entry_date": "2026-07-02", "entry_price": 70.0}}

        answered = self.action(self.preview(SAMPLE, res), "NFLX")
        self.assertEqual(answered["action"], "create")

        self.apply(SAMPLE, resolutions=res)
        nflx = self.trades()["NFLX"]
        self.assertEqual(nflx["entry_date"], "2026-07-02")
        self.assertEqual(nflx["exit_date"], "2026-08-24")
        self.assertEqual(nflx["win_loss"], "WIN")

    def test_a_hand_logged_open_position_is_closed_not_duplicated(self):
        """The case Drew named: the CSV window opens after the buy, but the
        position is already in Horizon because he typed it in."""
        self.client.post("/api/trades", json={
            "ticker": "NFLX", "entry_date": "2026-07-02", "entry_price": 70.0,
            "shares": 0.5205, "currency": "USD", "entry_fee": 0.5,
        })
        plan = self.preview(SAMPLE)
        nflx = self.action(plan, "NFLX")
        self.assertEqual(nflx["action"], "update", nflx["reason"])
        self.assertIn("exit_date", nflx["targets"][0]["diff"])

        self.apply(SAMPLE, accept=[nflx["key"]])
        rows = [t for t in self.all_trades() if t["ticker"] == "NFLX"]
        self.assertEqual(len(rows), 1, "the hand-logged row was duplicated")
        self.assertEqual(rows[0]["exit_date"], "2026-08-24")
        self.assertEqual(rows[0]["entry_price"], 70.0)   # entry left alone

    def test_a_declined_sale_is_not_asked_about_again(self):
        key = self.action(self.preview(SAMPLE), "NFLX")["key"]
        self.apply(SAMPLE, resolutions={key: {"mode": "ignore"}})

        # No answer supplied this time — the earlier decision should hold.
        plan = self.preview(SAMPLE)
        self.assertEqual(plan["needs_input"], [])
        self.assertEqual(plan["fills_new"], 0)
        self.assertNotIn("NFLX", self.trades())

    def test_a_hand_logged_row_is_adopted_when_the_file_contains_its_buy(self):
        """An all-time CSV reaches back past rows Drew typed in himself. Those
        rows should be corrected in place — with the broker's real price and
        commission — not logged a second time."""
        self.client.post("/api/trades", json={
            "ticker": "NKE", "entry_date": "2026-04-16", "entry_price": 45.95,
            "shares": 0.34, "currency": "USD", "entry_fee": 0,
        })
        csv_text = _txn([("2026-04-16", "NIKE INC", "Buy", "NKE", "0.34", "45.50", "-0.155")])

        plan = self.preview(csv_text)
        nke = self.action(plan, "NKE")
        self.assertEqual(nke["action"], "update", nke["reason"])

        self.apply(csv_text)
        rows = [t for t in self.all_trades() if t["ticker"] == "NKE"]
        self.assertEqual(len(rows), 1, "the hand-logged row was duplicated")
        self.assertAlmostEqual(rows[0]["shares"], 0.34, places=6)
        self.assertAlmostEqual(rows[0]["entry_price"], 45.50, places=6)
        self.assertAlmostEqual(rows[0]["entry_fee"], 0.155, places=6)

    # -- adding to a position ---------------------------------------------

    def test_adding_to_a_position_reaverages_the_entry(self):
        nflx = {self.action(self.preview(SAMPLE), "NFLX")["key"]: {"mode": "ignore"}}
        self.apply(SAMPLE, resolutions=nflx)
        first = self.trades()["AGX"]
        self.assertAlmostEqual(first["shares"], 0.1586, places=6)

        more = _txn([("2026-09-20", "ARGAN INC", "Buy", "AGX", "0.1", "400.00", "-0.4")])
        plan = self.preview(more)
        agx = self.action(plan, "AGX")
        self.assertEqual(agx["action"], "update")
        self.assertIn("shares", agx["targets"][0]["diff"])

        self.apply(more)
        after = self.trades()["AGX"]
        self.assertAlmostEqual(after["shares"], 0.2586, places=6)
        self.assertAlmostEqual(after["entry_price"],
                               (0.1586 * 422.28 + 0.1 * 400.0) / 0.2586, places=6)
        self.assertAlmostEqual(after["entry_fee"], 0.9301301289728 + 0.4, places=6)
        self.assertIsNone(after["exit_date"])

    def test_selling_out_closes_the_position(self):
        nflx = {self.action(self.preview(SAMPLE), "NFLX")["key"]: {"mode": "ignore"}}
        self.apply(SAMPLE, resolutions=nflx)

        out = _txn([("2026-09-20", "SHARKNINJA INC", "Sell", "SN", "-0.4171", "180.00", "-1.05")])
        self.apply(out)
        sn = self.trades()["SN"]
        self.assertEqual(sn["exit_date"], "2026-09-20")
        self.assertEqual(sn["exit_price"], 180.0)
        self.assertEqual(sn["win_loss"], "WIN")
        self.assertEqual(sn["days_held"], 6)
        self.assertEqual(len([t for t in self.all_trades() if t["ticker"] == "SN"]), 1)

    # -- partial exits ----------------------------------------------------

    def test_partial_exit_splits_into_a_closed_and_an_open_row(self):
        nflx = {self.action(self.preview(SAMPLE), "NFLX")["key"]: {"mode": "ignore"}}
        self.apply(SAMPLE, resolutions=nflx)

        half = _txn([("2026-09-20", "TJX COMPANIES INC", "Sell", "TJX", "-0.2", "150.00", "-0.3")])
        plan = self.preview(half)
        tjx = self.action(plan, "TJX")
        self.assertEqual(tjx["question"], "partial_exit")
        self.assertEqual(len(tjx["targets"]), 2)

        self.apply(half)
        rows = sorted([t for t in self.all_trades() if t["ticker"] == "TJX"],
                      key=lambda t: t["exit_date"] or "")
        self.assertEqual(len(rows), 2)
        open_row = [r for r in rows if not r["exit_date"]][0]
        closed_row = [r for r in rows if r["exit_date"]][0]
        self.assertAlmostEqual(closed_row["shares"], 0.2, places=6)
        self.assertAlmostEqual(open_row["shares"], 0.499 + 0.0002 - 0.2, places=6)
        self.assertEqual(closed_row["win_loss"], "WIN")
        # Entry commission is shared out, not charged twice.
        total_entry_fee = sum(r["entry_fee"] for r in rows)
        self.assertAlmostEqual(total_entry_fee, 0.9373071136308 + 0.00037579399959999997,
                               places=6)

    def test_choosing_to_shrink_instead_leaves_one_open_row(self):
        nflx = {self.action(self.preview(SAMPLE), "NFLX")["key"]: {"mode": "ignore"}}
        self.apply(SAMPLE, resolutions=nflx)

        half = _txn([("2026-09-20", "TJX COMPANIES INC", "Sell", "TJX", "-0.2", "150.00", "-0.3")])
        key = self.action(self.preview(half), "TJX")["key"]
        self.apply(half, resolutions={key: {"mode": "reduce"}})

        rows = [t for t in self.all_trades() if t["ticker"] == "TJX"]
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["exit_date"])
        self.assertAlmostEqual(rows[0]["shares"], 0.2992, places=6)

    def test_a_split_that_later_goes_flat_collapses_to_one_closed_row(self):
        nflx = {self.action(self.preview(SAMPLE), "NFLX")["key"]: {"mode": "ignore"}}
        self.apply(SAMPLE, resolutions=nflx)
        self.apply(_txn([("2026-09-20", "TJX", "Sell", "TJX", "-0.2", "150.00", "-0.3")]))
        self.assertEqual(len([t for t in self.all_trades() if t["ticker"] == "TJX"]), 2)

        self.apply(_txn([("2026-09-25", "TJX", "Sell", "TJX", "-0.2992", "160.00", "-0.48")]))
        rows = [t for t in self.all_trades() if t["ticker"] == "TJX"]
        self.assertEqual(len(rows), 1, "the open half should have been folded in")
        self.assertEqual(rows[0]["exit_date"], "2026-09-25")
        self.assertAlmostEqual(rows[0]["shares"], 0.4992, places=6)
        # The whole ledger survived the collapse.
        with dbmod.get_db() as conn:
            n = conn.execute("SELECT COUNT(*) c FROM trade_fills WHERE ticker='TJX'").fetchone()["c"]
        self.assertEqual(n, 4)

    # -- overlapping windows ----------------------------------------------

    def test_an_all_time_file_after_a_monthly_one_only_adds_what_is_new(self):
        nflx_key = self.action(self.preview(SAMPLE), "NFLX")["key"]
        self.apply(SAMPLE, resolutions={nflx_key: {"mode": "ignore"}})
        before = {t["ticker"]: t["id"] for t in self.all_trades()}

        # Same August–September rows, plus an older AGX buy and a newer SN buy.
        all_time = SAMPLE.rstrip("\n") + "\n" + "\n".join([
            "Transaction History,Data,2026-09-20,U***56746,SHARKNINJA INC,Buy,SN,0.1,150.00,USD,0,-0.15,0",
            "Transaction History,Data,2026-06-05,U***56746,LOCKHEED MARTIN,Buy,LMT,0.2,520.15,USD,0,-1.04,0",
        ]) + "\n"

        plan = self.preview(all_time)
        self.assertEqual(plan["fills_known"], 9)
        self.assertEqual(plan["fills_new"], 2)
        self.assertEqual({a["ticker"] for a in plan["actions"]
                          if a["action"] in ("create", "update")}, {"SN", "LMT"})

        self.apply(all_time, resolutions={nflx_key: {"mode": "ignore"}})
        after = self.trades()
        # Untouched rows keep their identity — no delete-and-recreate churn.
        self.assertEqual(after["DECK"]["id"], before["DECK"])
        self.assertAlmostEqual(after["SN"]["shares"], 0.5171, places=6)
        self.assertIn("LMT", after)

    def test_importing_an_older_file_second_lands_in_the_same_place(self):
        """Order independence: the numbers don't depend on which window you
        pasted first."""
        newer = _txn([("2026-09-10", "ARGAN INC", "Buy", "AGX", "0.1", "400.00", "-0.4")])
        older = _txn([("2026-09-03", "ARGAN INC", "Buy", "AGX", "0.2", "420.00", "-0.84")])

        self.apply(newer)
        self.apply(older)
        forwards = self.trades()["AGX"]

        self.setUp()
        self.apply(older)
        self.apply(newer)
        backwards = self.trades()["AGX"]

        for field in ("shares", "entry_price", "entry_fee", "entry_date"):
            self.assertEqual(forwards[field], backwards[field], field)
        self.assertEqual(forwards["entry_date"], "2026-09-03")
        self.assertAlmostEqual(forwards["shares"], 0.3, places=6)

    def test_deleting_a_trade_lets_the_next_import_rebuild_it(self):
        """Deleting a row cascades its fills away, which is the escape hatch: if
        an import got a position wrong, bin the row and paste the file again."""
        nflx = {self.action(self.preview(SAMPLE), "NFLX")["key"]: {"mode": "ignore"}}
        self.apply(SAMPLE, resolutions=nflx)
        deck_id = self.trades()["DECK"]["id"]

        self.client.delete(f"/api/trades/{deck_id}")
        with dbmod.get_db() as conn:
            left = conn.execute(
                "SELECT COUNT(*) c FROM trade_fills WHERE ticker='DECK'").fetchone()["c"]
        self.assertEqual(left, 0, "fills should cascade with the trade")

        plan = self.preview(SAMPLE)
        self.assertEqual(self.action(plan, "DECK")["action"], "create")
        self.apply(SAMPLE, resolutions=nflx)
        self.assertAlmostEqual(self.trades()["DECK"]["shares"], 0.8314, places=6)

    # -- selective apply --------------------------------------------------

    def test_accept_list_limits_what_is_written(self):
        plan = self.preview(SAMPLE)
        deck = self.action(plan, "DECK")
        result = self.apply(SAMPLE, accept=[deck["key"]])
        self.assertEqual(result["created"], 1)
        self.assertEqual(set(self.trades()), {"DECK"})

        # The rest is still pending, not swallowed.
        self.assertEqual(self.preview(SAMPLE)["fills_new"], 7)


if __name__ == "__main__":
    unittest.main()
