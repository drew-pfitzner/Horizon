import os
import sqlite3
import tempfile
from datetime import datetime
from flask import Blueprint, request, jsonify, Response, send_file
import json

from db import get_db
from config import SMART_MONEY_DB

bp = Blueprint("backup", __name__)

BACKUP_VERSION = 1
TABLES = ["market_check", "valuations", "researched_stocks", "trades", "settings"]


def _dump_table(db, table):
    rows = db.execute(f"SELECT * FROM {table}").fetchall()
    return [dict(r) for r in rows]


@bp.route("/export", methods=["GET"])
def export_data():
    with get_db() as db:
        payload = {
            "version": BACKUP_VERSION,
            "exported_at": datetime.utcnow().isoformat() + "Z",
            "tables": {t: _dump_table(db, t) for t in TABLES},
        }
    body = json.dumps(payload, indent=2, default=str)
    fname = f"horizon_backup_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.json"
    return Response(
        body,
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


@bp.route("/import", methods=["POST"])
def import_data():
    payload = request.get_json(force=True, silent=True)
    if not payload or not isinstance(payload, dict):
        return jsonify({"success": False, "error": "invalid JSON body"}), 400
    if payload.get("version") != BACKUP_VERSION:
        return jsonify({"success": False, "error": f"unsupported backup version: {payload.get('version')}"}), 400
    tables = payload.get("tables")
    if not isinstance(tables, dict):
        return jsonify({"success": False, "error": "missing 'tables' object"}), 400

    counts = {}
    with get_db() as db:
        # foreign_keys is ON; researched_stocks references valuations.
        # Disable for the duration of the wipe + reload to allow any ordering.
        db.execute("PRAGMA foreign_keys=OFF")
        try:
            for t in TABLES:
                db.execute(f"DELETE FROM {t}")
            for t in TABLES:
                rows = tables.get(t, [])
                if not rows:
                    counts[t] = 0
                    continue
                cols = list(rows[0].keys())
                placeholders = ",".join("?" for _ in cols)
                col_list = ",".join(cols)
                sql = f"INSERT INTO {t} ({col_list}) VALUES ({placeholders})"
                db.executemany(sql, [tuple(r.get(c) for c in cols) for r in rows])
                counts[t] = len(rows)
        finally:
            db.execute("PRAGMA foreign_keys=ON")

    return jsonify({"success": True, "data": {"imported": counts}})


@bp.route("/smart-money/export", methods=["GET"])
def export_smart_money():
    if not SMART_MONEY_DB.exists():
        return jsonify({"success": False, "error": "smart_money.db not found"}), 404
    fname = f"smart_money_backup_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.db"
    # Use SQLite backup API to a temp file so WAL state is consolidated and readers aren't disturbed.
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    try:
        src = sqlite3.connect(f"file:{SMART_MONEY_DB}?mode=ro", uri=True)
        dst = sqlite3.connect(tmp.name)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        return send_file(
            tmp.name,
            mimetype="application/octet-stream",
            as_attachment=True,
            download_name=fname,
        )
    except Exception as e:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route("/smart-money/import", methods=["POST"])
def import_smart_money():
    file = request.files.get("file")
    if not file:
        return jsonify({"success": False, "error": "no file uploaded"}), 400

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    try:
        file.save(tmp.name)
        # Validate it's a SQLite DB with the expected tables.
        try:
            check = sqlite3.connect(f"file:{tmp.name}?mode=ro", uri=True)
            try:
                tables = {r[0] for r in check.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()}
            finally:
                check.close()
        except sqlite3.DatabaseError as e:
            return jsonify({"success": False, "error": f"not a valid SQLite database: {e}"}), 400
        required = {"gurus", "holdings"}
        missing = required - tables
        if missing:
            return jsonify({"success": False, "error": f"missing tables: {sorted(missing)}"}), 400

        # Restore via SQLite backup into the target DB so concurrent readers fail gracefully
        # rather than reading a half-written file.
        SMART_MONEY_DB.parent.mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(f"file:{tmp.name}?mode=ro", uri=True)
        dst = sqlite3.connect(str(SMART_MONEY_DB))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        return jsonify({"success": True, "data": {"restored": True}})
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
