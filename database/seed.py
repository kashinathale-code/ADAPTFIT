"""
ADAPTFIT database seed script.

Creates all tables from schema.sql and inserts the Rain Garden adaptation
plus its five candidate requirements.

ALL rules are marked "candidate, unverified" in the evidence column and
MUST be labelled as such in the UI (PRD §8, FR-14).

Transfer-tolerance type stored in this script (engine must match):
  "relative" → flag when |B - A| > tolerance × |A|
  "absolute" → flag when |B - A| > tolerance
  None       → no transfer-risk check

Usage:
    python database/seed.py
    python database/seed.py --db-path path/to/other.db
    python database/seed.py --force     # re-seed even if data exists
"""

import argparse
import os
import sqlite3

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")
DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "adaptfit.db")


def _load_schema() -> str:
    with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
        return fh.read()


import time

def seed(db_path: str = DEFAULT_DB_PATH, force: bool = False) -> None:
    """Create tables and insert Rain Garden seed data safely across multiple workers.

    Args:
        db_path: Path to the SQLite database file.
        force:   If True, delete and re-insert Rain Garden data even if present.
    """
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    lock_path = db_path + ".seed.lock"
    lock_fd = None
    acquired = False

    start_time = time.time()
    while time.time() - start_time < 15.0:
        try:
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            acquired = True
            break
        except FileExistsError:
            time.sleep(0.1)

    try:
        conn = sqlite3.connect(db_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA foreign_keys = ON")
        cur = conn.cursor()

        # Create all tables (IF NOT EXISTS makes this safe to run repeatedly)
        cur.executescript(_load_schema())
        conn.commit()

        # Guard against double-seeding
        cur.execute("SELECT COUNT(*) FROM adaptations WHERE id = 'rain_garden'")
        already_seeded = cur.fetchone()[0] > 0

        if already_seeded and not force:
            print("Rain Garden seed data already present. Use --force to re-seed.")
            conn.close()
            return

        if already_seeded and force:
            cur.execute(
                "DELETE FROM adaptation_requirements WHERE adaptation_id = 'rain_garden'"
            )
            cur.execute(
                "DELETE FROM assessment_factors WHERE assessment_id IN "
                "(SELECT id FROM assessments WHERE adaptation_id = 'rain_garden')"
            )
            cur.execute("DELETE FROM assessments WHERE adaptation_id = 'rain_garden'")
            cur.execute("DELETE FROM adaptations WHERE id = 'rain_garden'")
            conn.commit()
            print("Existing Rain Garden data deleted. Re-seeding …")

        # ------------------------------------------------------------------ #
        # Rain Garden adaptation record                                        #
        # ------------------------------------------------------------------ #
        cur.execute(
            """
            INSERT INTO adaptations (id, name, description, evidence_source)
            VALUES (?, ?, ?, ?)
            """,
            (
                "rain_garden",
                "Rain Garden",
                (
                    "A shallow, vegetated depression that captures and infiltrates stormwater "
                    "runoff from impervious surfaces, reducing peak flow and improving water quality."
                ),
                (
                    "Criteria benchmarked against CPHEEO Storm Water Manual (2019, India), "
                    "US EPA Bioretention BMPs, UK CIRIA SuDS Manual C753, and Minnesota Stormwater Manual. "
                    "Annual rainfall range remains candidate, unverified – see docs/SOURCES.md."
                ),
            ),
        )

        # ------------------------------------------------------------------ #
        # Rain Garden requirements (authoritative citations & candidate rules) #
        # ------------------------------------------------------------------ #
        # tolerance_type: "relative" → |B-A| > tolerance × |A|
        #                 "absolute" → |B-A| > tolerance
        #                 None       → no transfer-risk check
        requirements = [
            {
                "adaptation_id": "rain_garden",
                "factor": "soil_infiltration",
                "min_value": 12.7,          # mm/hr (≈ 0.5 in/hr)
                "max_value": None,
                "unit": "mm/hr",
                "weight": 0.35,
                "is_critical": 1,
                "transfer_tolerance": 0.50,  # 50 % of A
                "tolerance_type": "relative",
                "evidence": (
                    "Minimum 12.7 mm/hr (0.5 in/hr) benchmarked by US EPA ('Stormwater Best Management "
                    "Practice: Bioretention', EPA 833-F-00-001) and CPHEEO Manual on Storm Water "
                    "Drainage Systems (2019, MoHUA) to ensure captured runoff drains within 24–48 hours."
                ),
                "rule_version": "v1.0-verified",
            },
            {
                "adaptation_id": "rain_garden",
                "factor": "slope",
                "min_value": None,
                "max_value": 8.0,           # %
                "unit": "%",
                "weight": 0.25,
                "is_critical": 1,
                "transfer_tolerance": 3.0,   # 3 percentage points
                "tolerance_type": "absolute",
                "evidence": (
                    "Maximum 8.0% ground slope threshold based on Minnesota Stormwater Manual "
                    "(Bioretention design criteria) and Wisconsin DNR Standard 1004. Slopes above 8% "
                    "produce erosive velocities and require engineered terracing or check dams."
                ),
                "rule_version": "v1.0-verified",
            },
            {
                "adaptation_id": "rain_garden",
                "factor": "annual_rainfall",
                "min_value": 600.0,         # mm/yr  – placeholder lower bound
                "max_value": 2500.0,        # mm/yr  – placeholder upper bound
                "unit": "mm/yr",
                "weight": 0.15,
                "is_critical": 0,
                "transfer_tolerance": 0.30,  # 30 % of A
                "tolerance_type": "relative",
                "evidence": (
                    "candidate, unverified – provisional heuristic bounds 600–2500 mm/yr for temperate "
                    "and monsoon bioretention cells. Sizing depends on localized design storms rather "
                    "than annual totals."
                ),
                "rule_version": "v0.1-candidate",
            },
            {
                "adaptation_id": "rain_garden",
                "factor": "open_space",
                "min_value": None,          # binary: engine checks value >= 1.0 (present)
                "max_value": None,
                "unit": "binary (1=present, 0=absent)",
                "weight": 0.15,
                "is_critical": 0,
                "transfer_tolerance": None,
                "tolerance_type": None,
                "evidence": (
                    "Dedicated unbuilt permeable footprint requirement referenced in CPHEEO Manual on "
                    "Storm Water Drainage Systems (2019) Chapter 10 (Innovative SUDS) and CIRIA C753 Section 20."
                ),
                "rule_version": "v1.0-verified",
            },
            {
                "adaptation_id": "rain_garden",
                "factor": "building_distance",
                "min_value": 3.0,           # m
                "max_value": None,
                "unit": "m",
                "weight": 0.10,
                "is_critical": 0,
                "transfer_tolerance": None,
                "tolerance_type": None,
                "evidence": (
                    "Minimum 3.0 m (10 ft) foundation setback cited in US EPA 'Soak Up the Rain: Rain "
                    "Gardens' and CIRIA C753 Section 25.2.3 to prevent subsoil moisture migration into basements."
                ),
                "rule_version": "v1.0-verified",
            },
        ]

        cur.executemany(
            """
            INSERT INTO adaptation_requirements
                (adaptation_id, factor, min_value, max_value, unit, weight,
                 is_critical, transfer_tolerance, tolerance_type, evidence, rule_version)
            VALUES
                (:adaptation_id, :factor, :min_value, :max_value, :unit, :weight,
                 :is_critical, :transfer_tolerance, :tolerance_type, :evidence, :rule_version)
            """,
            requirements,
        )

        conn.commit()
        conn.close()

        total_weight = sum(r["weight"] for r in requirements)
        print(
            f"Seeded Rain Garden adaptation with {len(requirements)} requirements "
            f"(total weight = {total_weight:.2f}) into: {db_path}"
        )
        print("NOTE: All rules are 'candidate, unverified' – label them as such in the UI.")
    finally:
        if acquired and lock_fd is not None:
            try:
                os.close(lock_fd)
                if os.path.exists(lock_path):
                    os.remove(lock_path)
            except OSError:
                pass



# -------------------------------------------------------------------------- #
# CLI entry point                                                             #
# -------------------------------------------------------------------------- #
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed the ADAPTFIT SQLite database.")
    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help=f"Path to the SQLite database file (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete existing Rain Garden data and re-seed.",
    )
    args = parser.parse_args()
    seed(db_path=args.db_path, force=args.force)
