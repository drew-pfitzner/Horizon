"""Auto-prefill research + valuation from SEC EDGAR.

GET /api/prefill/<ticker> runs the same engine as research_cli.py and returns:
  - flags:      research-checklist booleans keyed by DB field name
  - details:    human-readable value per flag (e.g. "31.8%")
  - valuation:  roe1..5 / payout1..5 (latest first, payout as %), equity, shares, price
  - financial / veto / verdict / assessment metadata for UI warnings

Network-bound (SEC + Yahoo); intended for an explicit "Prefill" button click.
"""
from flask import Blueprint, jsonify

import research_cli as engine

bp = Blueprint("prefill", __name__)


@bp.route("/<ticker>", methods=["GET"])
def prefill(ticker):
    ticker = (ticker or "").strip().upper()
    if not ticker:
        return jsonify({"success": False, "error": "ticker required"}), 400
    try:
        data = engine.to_horizon_prefill(engine.analyze(ticker))
    except Exception as e:  # network / parse failures shouldn't 500 the UI
        return jsonify({"success": False, "error": f"prefill failed: {e}"}), 200

    if data.get("error"):
        return jsonify({"success": False, "error": data["error"]}), 200
    return jsonify({"success": True, "data": data})
