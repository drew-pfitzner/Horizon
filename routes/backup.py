from datetime import datetime
from flask import Blueprint, request, jsonify, Response
import json

from db import get_db

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
