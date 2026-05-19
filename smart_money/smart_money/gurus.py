import csv
import os
import shutil
import time
from smart_money.config import GURU_LIST_PATH, FETCH_DELAY, require_sec_identity
from smart_money.db import get_db


SEED_GURU_LIST_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "seed",
    "guru_list.csv",
)


def _ensure_guru_list():
    """Copy the tracked seed CSV into the writable data dir on first run.

    The CIK resolver writes back to GURU_LIST_PATH, so the working copy must
    live in an ignored directory to keep the repo clean.
    """
    if os.path.exists(GURU_LIST_PATH):
        return
    os.makedirs(os.path.dirname(GURU_LIST_PATH), exist_ok=True)
    if not os.path.exists(SEED_GURU_LIST_PATH):
        raise FileNotFoundError(
            f"Seed guru list not found at {SEED_GURU_LIST_PATH}"
        )
    shutil.copyfile(SEED_GURU_LIST_PATH, GURU_LIST_PATH)


def load_guru_list():
    _ensure_guru_list()
    gurus = []
    with open(GURU_LIST_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            gurus.append(row)
    return gurus


def seed_gurus_to_db():
    gurus = load_guru_list()
    with get_db() as conn:
        for g in gurus:
            cik = g.get("cik") or None
            status = g.get("status", "")
            active = 1 if status == "resolved" and cik else 0
            notes = "no 13F filings" if status == "no_13f" else None
            existing = conn.execute(
                "SELECT id FROM gurus WHERE name = ? AND firm = ?",
                (g["name"], g["firm"])
            ).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO gurus (name, firm, cik, active, notes) VALUES (?, ?, ?, ?, ?)",
                    (g["name"], g["firm"], cik, active, notes)
                )
    print(f"Seeded {len(gurus)} gurus into database")


def resolve_ciks(dry_run=False):
    from edgar import set_identity, get_cik_lookup_data
    set_identity(require_sec_identity())

    # Load the full SEC entity lookup (~1M entries)
    print("Loading SEC entity database...")
    lookup_df = get_cik_lookup_data()
    # Normalize names for matching
    lookup_df["name_upper"] = lookup_df["name"].str.upper().str.strip()

    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name, firm FROM gurus WHERE (cik IS NULL OR cik = '') AND notes IS NULL"
        ).fetchall()

    if not rows:
        print("All gurus already have CIKs resolved.")
        return

    print(f"Resolving CIKs for {len(rows)} gurus...")
    resolved = 0
    failed = []

    for row in rows:
        guru_id, name, firm = row["id"], row["name"], row["firm"]
        candidates = _search_cik_candidates(firm, name, lookup_df)

        found = False
        for cik in candidates:
            # Check if this CIK is already assigned to another guru
            with get_db() as conn:
                existing = conn.execute(
                    "SELECT name FROM gurus WHERE cik = ? AND id != ?",
                    (cik, guru_id)
                ).fetchone()
            if existing:
                continue  # Skip, already used by another guru entry

            has_13f = _verify_13f_filer(cik)
            if has_13f:
                resolved += 1
                found = True
                if not dry_run:
                    with get_db() as conn:
                        conn.execute(
                            "UPDATE gurus SET cik = ?, active = 1 WHERE id = ?",
                            (cik, guru_id)
                        )
                print(f"  [OK] {name} ({firm}) -> CIK {cik}")
                break
            time.sleep(FETCH_DELAY)

        if not found:
            reason = "no 13F filings" if candidates else "CIK not found"
            if not dry_run:
                with get_db() as conn:
                    conn.execute(
                        "UPDATE gurus SET active = 0, notes = ? WHERE id = ?",
                        (reason, guru_id)
                    )
            failed.append((name, firm, reason))
            print(f"  [FAIL] {name} ({firm}) -> {reason}")

        time.sleep(FETCH_DELAY)

    print(f"\nResolved: {resolved}/{len(rows)}")
    if failed:
        print(f"Skipped/failed ({len(failed)}):")
        for name, firm, reason in failed:
            print(f"  - {name} ({firm}): {reason}")

    _update_csv_with_ciks()


def _search_cik_candidates(firm, name, lookup_df):
    """Search SEC entity database and return a list of candidate CIKs to check for 13F filings."""
    seen = set()
    candidates = []

    def _add(cik_val):
        cik_str = str(cik_val).zfill(10)
        if cik_str not in seen:
            seen.add(cik_str)
            candidates.append(cik_str)

    # Try exact firm match first
    firm_upper = firm.upper().strip()
    exact = lookup_df[lookup_df["name_upper"] == firm_upper]
    for _, row in exact.iterrows():
        _add(row["cik"])

    # Try with common entity suffixes appended
    for suffix in [" INC", " LLC", " L.P.", " LP", " INC."]:
        exact_suffix = lookup_df[lookup_df["name_upper"] == firm_upper + suffix]
        for _, row in exact_suffix.iterrows():
            _add(row["cik"])

    # Try all search term variations with contains
    search_terms = _generate_search_terms(firm)
    for term in search_terms:
        term_upper = term.upper().strip()
        if len(term_upper) < 5:
            continue
        matches = lookup_df[lookup_df["name_upper"].str.contains(term_upper, na=False, regex=False)]
        # Sort by name length (shorter = more likely to be the parent entity)
        matches = matches.sort_values(by="name", key=lambda x: x.str.len())
        for _, row in matches.head(10).iterrows():
            _add(row["cik"])

    return candidates[:20]  # Cap to avoid too many API calls


def _generate_search_terms(firm):
    """Generate search term variations from a firm name."""
    terms = [firm]

    # Strip common suffixes and try
    for suffix in [" LLC", " LP", " L.P.", " Inc", " Inc.", " Corp", " Corp.",
                   " Fund", " Management", " Capital", " Partners", " Advisors",
                   " Group", " Investment", " Investments", " Asset Management"]:
        if firm.lower().endswith(suffix.lower()):
            terms.append(firm[:len(firm) - len(suffix)])

    # Try firm name + common entity type suffixes
    base = terms[-1] if len(terms) > 1 else firm
    for suffix in [" CAPITAL MANAGEMENT", " MANAGEMENT", " CAPITAL", " LP", " L.P."]:
        candidate = base + suffix
        if candidate.upper() != firm.upper():
            terms.append(candidate)

    return terms


def _verify_13f_filer(cik):
    """Check if a CIK has any 13F-HR filings on record."""
    from edgar import Company
    try:
        company = Company(cik)
        filings = company.get_filings(form="13F-HR")
        return filings is not None and len(filings) > 0
    except Exception:
        return False


def _update_csv_with_ciks():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT name, firm, cik, "
            "CASE WHEN active = 1 THEN 'resolved' "
            "WHEN notes IS NOT NULL THEN 'no_13f' ELSE 'pending' END as status "
            "FROM gurus ORDER BY name"
        ).fetchall()

    with open(GURU_LIST_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "firm", "cik", "status"])
        for r in rows:
            writer.writerow([r["name"], r["firm"], r["cik"] or "", r["status"]])


def list_gurus(show_all=False):
    with get_db() as conn:
        if show_all:
            rows = conn.execute(
                "SELECT name, firm, cik, active, notes, last_updated FROM gurus ORDER BY name"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT name, firm, cik, active, notes, last_updated FROM gurus "
                "WHERE active = 1 ORDER BY name"
            ).fetchall()
    return rows
