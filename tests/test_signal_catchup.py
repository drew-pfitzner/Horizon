"""Tests for the alert catch-up window and the duplicate-send guard.

Run from the Horizon directory:

    venv/bin/python -m unittest discover -s tests -t . -v

Same temp-DB approach as test_ibkr_import: HORIZON_DB_PATH has to be set before
anything imports config, so it's poked in at module import time. It's a
setdefault because config caches the path in a module constant — under discovery
whichever test module loads first wins, and both must agree on the file. (Hence
the filename: it sorts after test_ibkr_import.py.)

Nothing here touches the network: prices and the signal series are supplied, and
notify.push — the ntfy transport — is replaced with a recorder.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP = tempfile.mkdtemp(prefix="horizon-test-")
os.environ.setdefault("HORIZON_DB_PATH", str(Path(_TMP) / "horizon.db"))

import db as dbmod                    # noqa: E402
import notify                         # noqa: E402
import alert_job                      # noqa: E402

# A week of daily bars: Thu, Fri, then Mon — the weekend is the point.
THU, FRI, MON = "2026-09-10", "2026-09-11", "2026-09-14"
BARS = [{"date": d, "close": 100.0} for d in ("2026-09-08", "2026-09-09", THU, FRI, MON)]


def _series(*signal_dates, direction="buy"):
    """Signal series aligned to BARS, with edges on the given bar dates."""
    out = []
    for b in BARS:
        row = {"date": b["date"], "close": b["close"], "rsi": 30.0, "k": 15.0,
               "d": 12.0, "buy": False, "sell": False}
        if b["date"] in signal_dates:
            row[direction] = True
        out.append(row)
    return out


class CatchupTest(unittest.TestCase):
    def setUp(self):
        path = Path(os.environ["HORIZON_DB_PATH"])
        for p in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
            if p.exists():
                p.unlink()
        dbmod.init_db()

        self.sent = []
        self.push_ok = True
        self._real_push = notify.push
        self._real_fetch = alert_job.fetch_history
        self._real_evaluate = alert_job.evaluate

        def fake_push(title, body, priority=None, tags=None):
            self.sent.append((title, body))
            return (True, None) if self.push_ok else (False, "ntfy down")

        notify.push = fake_push
        alert_job.fetch_history = lambda ticker: (list(BARS), "test")
        dbmod.set_setting("ntfy_topic", "test-topic")

    def tearDown(self):
        notify.push = self._real_push
        alert_job.fetch_history = self._real_fetch
        alert_job.evaluate = self._real_evaluate

    # -- helpers ----------------------------------------------------------

    def watch(self, ticker="AAPL", *, bucket="BUY", last_checked=THU):
        """A watch that watch_sync will keep, plus its watermark.

        The lists are derived, so the ticker needs a backing row — fresh TRADE
        research puts it in the Buy bucket — or sync() would soft-delete it.
        """
        from datetime import date
        today = date.today().isoformat()
        with dbmod.get_db() as db:
            if bucket == "BUY":
                db.execute(
                    "INSERT INTO researched_stocks (ticker, date_researched, decision, "
                    "updated_at) VALUES (?, ?, 'TRADE', ?)", (ticker, today, today))
            else:
                db.execute(
                    "INSERT INTO trades (ticker, strategy, entry_date, entry_price, shares) "
                    "VALUES (?, 'TRADE', ?, 100.0, 1)", (ticker, today))
            db.execute(
                "INSERT INTO alert_watch (ticker, bucket, kind, active, created_at, "
                "last_checked_bar) VALUES (?, ?, 'Trade', 1, ?, ?)",
                (ticker, bucket, today, last_checked))

    def signals_on(self, *dates, direction="buy"):
        alert_job.evaluate = lambda bars, kind=None, params=None: _series(
            *dates, direction=direction)

    def watermark(self, ticker="AAPL"):
        with dbmod.get_db() as db:
            row = db.execute("SELECT last_checked_bar FROM alert_watch WHERE ticker = ?",
                             (ticker,)).fetchone()
        return row["last_checked_bar"]

    def log_rows(self):
        with dbmod.get_db() as db:
            return [dict(r) for r in db.execute(
                "SELECT ticker, bar_date, signal_dir, ok FROM alert_log").fetchall()]

    # -- business-day arithmetic ------------------------------------------

    def test_weekend_does_not_age_a_signal(self):
        self.assertEqual(alert_job._business_days_between(FRI, MON), 1)
        self.assertEqual(alert_job._business_days_between(THU, MON), 2)
        self.assertEqual(alert_job._business_days_between(MON, MON), 0)

    # -- the catch-up window ----------------------------------------------

    def test_friday_signal_is_pushed_on_monday(self):
        dbmod.set_setting("alert_catchup_days", 2)
        self.watch(last_checked=THU)
        self.signals_on(FRI)

        summary = alert_job.run_checks()

        self.assertEqual(summary["fired"], 1)
        self.assertEqual(len(self.sent), 1)
        title, body = self.sent[0]
        self.assertEqual(title, "Horizon BUY: AAPL")
        # Not the latest close, so the body says which bar it came from.
        self.assertIn("from Fri 11 Sep close", body)
        self.assertEqual(self.watermark(), MON)

    def test_latest_bar_signal_carries_no_bar_note(self):
        dbmod.set_setting("alert_catchup_days", 2)
        self.watch(last_checked=THU)
        self.signals_on(MON)

        alert_job.run_checks()

        self.assertEqual(len(self.sent), 1)
        self.assertNotIn("from", self.sent[0][1])

    def test_signal_older_than_the_window_is_skipped_but_watermark_advances(self):
        dbmod.set_setting("alert_catchup_days", 1)
        self.watch(last_checked="2026-09-08")
        self.signals_on("2026-09-09")   # 3 business days before Monday

        summary = alert_job.run_checks()

        self.assertEqual(self.sent, [])
        self.assertEqual(summary["fired"], 0)
        self.assertEqual(summary["failed"], 0)
        self.assertEqual(self.log_rows(), [])
        # Advanced anyway, so the stale edge never surfaces again.
        self.assertEqual(self.watermark(), MON)
        self.assertTrue(any("stale" in line for line in alert_job.get_state()["output"]))

    def test_zero_window_means_latest_bar_only(self):
        dbmod.set_setting("alert_catchup_days", 0)
        self.watch(last_checked=THU)
        self.signals_on(FRI)

        alert_job.run_checks()

        self.assertEqual(self.sent, [])
        self.assertEqual(self.watermark(), MON)

    # -- duplicate guard ---------------------------------------------------

    def test_signal_already_in_the_log_is_not_resent(self):
        dbmod.set_setting("alert_catchup_days", 2)
        self.watch(last_checked=THU)
        self.signals_on(MON)
        with dbmod.get_db() as db:
            db.execute(
                "INSERT INTO alert_log (ticker, bucket, action, signal_dir, kind, "
                "bar_date, price, sent_at, transport, ok) VALUES "
                "('AAPL', 'BUY', 'BUY', 'BUY', 'Trade', ?, 100.0, '2026-09-14T20:00Z', "
                "'ntfy', 1)", (MON,))

        summary = alert_job.run_checks()

        self.assertEqual(self.sent, [])
        self.assertEqual(summary["fired"], 0)
        self.assertEqual(len(self.log_rows()), 1)   # no second row
        self.assertEqual(self.watermark(), MON)

    def test_a_failed_send_in_the_log_does_not_block_a_retry(self):
        dbmod.set_setting("alert_catchup_days", 2)
        self.watch(last_checked=THU)
        self.signals_on(MON)
        with dbmod.get_db() as db:
            db.execute(
                "INSERT INTO alert_log (ticker, bucket, action, signal_dir, kind, "
                "bar_date, price, sent_at, transport, ok, error) VALUES "
                "('AAPL', 'BUY', 'BUY', 'BUY', 'Trade', ?, 100.0, '2026-09-14T20:00Z', "
                "'ntfy', 0, 'ntfy down')", (MON,))

        alert_job.run_checks()

        self.assertEqual(len(self.sent), 1)

    # -- arming and retries ------------------------------------------------

    def test_freshly_armed_ticker_fires_nothing(self):
        dbmod.set_setting("alert_catchup_days", 2)
        self.watch(last_checked=None)
        self.signals_on(MON, FRI)

        summary = alert_job.run_checks()

        self.assertEqual(self.sent, [])
        self.assertEqual(summary["fired"], 0)
        self.assertEqual(self.watermark(), MON)

    def test_send_failure_leaves_the_watermark_for_a_retry(self):
        dbmod.set_setting("alert_catchup_days", 2)
        self.watch(last_checked=THU)
        self.signals_on(MON)
        self.push_ok = False

        summary = alert_job.run_checks()

        self.assertEqual(summary["failed"], 1)
        self.assertEqual(self.watermark(), THU)
        # The failed attempt is logged with ok = 0, so the dedupe guard won't
        # mistake it for a delivery on the retry.
        self.assertEqual(self.log_rows()[0]["ok"], 0)


if __name__ == "__main__":
    unittest.main()
