import os
import sys
import subprocess
import threading
import time
from pathlib import Path
from flask import Blueprint, jsonify


bp = Blueprint("system", __name__)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _in_docker() -> bool:
    return Path("/.dockerenv").exists() or os.getenv("HORIZON_IN_DOCKER") == "1"


def _git(*args, timeout=30):
    r = subprocess.run(
        ["git", *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def _git_available() -> bool:
    try:
        rc, _, _ = _git("rev-parse", "--is-inside-work-tree", timeout=5)
        return rc == 0
    except Exception:
        return False


def _collect_info(fetch_first: bool = False):
    if fetch_first:
        _git("fetch", "--quiet", timeout=60)
    _, sha, _ = _git("rev-parse", "--short", "HEAD")
    _, full_sha, _ = _git("rev-parse", "HEAD")
    _, branch, _ = _git("rev-parse", "--abbrev-ref", "HEAD")
    _, subj, _ = _git("log", "-1", "--pretty=%s")
    _, date, _ = _git("log", "-1", "--pretty=%cI")
    _, dirty, _ = _git("status", "--porcelain")
    dirty_files = [ln for ln in dirty.splitlines() if ln][:20] if dirty else []
    rc_b, behind, _ = _git("rev-list", "--count", "HEAD..@{u}")
    rc_a, ahead, _ = _git("rev-list", "--count", "@{u}..HEAD")
    return {
        "git_available": True,
        "in_docker": _in_docker(),
        "sha": sha,
        "full_sha": full_sha,
        "branch": branch,
        "subject": subj,
        "date": date,
        "dirty": bool(dirty),
        "dirty_files": dirty_files,
        "behind": int(behind) if rc_b == 0 and behind else 0,
        "ahead": int(ahead) if rc_a == 0 and ahead else 0,
        "has_upstream": rc_b == 0,
    }


@bp.route("/info", methods=["GET"])
def info():
    if not _git_available():
        return jsonify({
            "success": True,
            "data": {
                "git_available": False,
                "in_docker": _in_docker(),
                "message": "Not a git checkout — in-app updates unavailable. Use update.sh from the host.",
            },
        })
    return jsonify({"success": True, "data": _collect_info(fetch_first=False)})


@bp.route("/check", methods=["POST"])
def check():
    if not _git_available():
        return jsonify({"success": False, "error": "Not a git checkout"}), 400
    rc, out, err = _git("fetch", "--quiet", timeout=60)
    if rc != 0:
        return jsonify({"success": False, "error": f"git fetch failed: {err or out}"}), 500
    return jsonify({"success": True, "data": _collect_info(fetch_first=False)})


def _delayed_restart():
    time.sleep(0.8)
    if _in_docker():
        os._exit(0)
    try:
        os.execv(sys.executable, [sys.executable, *sys.argv])
    except Exception:
        os._exit(0)


@bp.route("/update", methods=["POST"])
def update():
    if not _git_available():
        return jsonify({"success": False, "error": "Not a git checkout"}), 400
    _, dirty, _ = _git("status", "--porcelain")
    if dirty:
        return jsonify({
            "success": False,
            "error": "Working tree has uncommitted changes; refusing to pull. Commit or stash first.",
        }), 400

    _, before, _ = _git("rev-parse", "HEAD")
    rc, out, err = _git("pull", "--ff-only", timeout=180)
    if rc != 0:
        return jsonify({"success": False, "error": f"git pull failed: {err or out}"}), 500
    _, after, _ = _git("rev-parse", "HEAD")

    changed = []
    deps_changed = False
    image_changed = False
    if before != after:
        rc2, files, _ = _git("diff", "--name-only", f"{before}..{after}")
        if rc2 == 0:
            changed = [f for f in files.splitlines() if f]
            deps_changed = "requirements.txt" in changed
            image_changed = any(f in ("Dockerfile", "docker-compose.yml") for f in changed)

    if before == after:
        return jsonify({
            "success": True,
            "data": {
                "before": before[:7],
                "after": after[:7],
                "changed_files": 0,
                "deps_changed": False,
                "image_changed": False,
                "restarting": False,
                "message": "Already up to date",
            },
        })

    threading.Thread(target=_delayed_restart, daemon=True).start()
    return jsonify({
        "success": True,
        "data": {
            "before": before[:7],
            "after": after[:7],
            "changed_files": len(changed),
            "deps_changed": deps_changed,
            "image_changed": image_changed,
            "in_docker": _in_docker(),
            "restarting": True,
        },
    })
