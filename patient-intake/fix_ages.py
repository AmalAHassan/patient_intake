"""
fix_ages.py — Recalculates the Age column in patients_enriched.csv
based on the actual DOB column.

Usage:
    python3 fix_ages.py

Input:  backend/data/patients_enriched.csv
Output: backend/data/patients_enriched.csv (overwritten in place)
"""
import csv
from datetime import date
from pathlib import Path

CSV_PATH = Path("backend/data/patients_enriched.csv")
TODAY    = date.today()

def calc_age(dob_str: str) -> int | None:
    """Parse MM/DD/YYYY and return age as of today."""
    try:
        month, day, year = map(int, dob_str.strip().split("/"))
        dob = date(year, month, day)
        age = TODAY.year - dob.year
        if (TODAY.month, TODAY.day) < (dob.month, dob.day):
            age -= 1
        return age
    except Exception:
        return None

def fix_ages(path: Path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys()) if rows else []

    fixed = 0
    skipped = 0
    for row in rows:
        dob = row.get("dob", "").strip()
        new_age = calc_age(dob)
        if new_age is not None:
            old_age = row.get("Age", "")
            if str(old_age) != str(new_age):
                row["Age"] = str(new_age)
                fixed += 1
        else:
            skipped += 1

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Done — {fixed} ages corrected, {skipped} rows skipped (bad DOB format)")
    print(f"Saved to {path}")

    # Spot check first 3 rows
    print("\nSpot check (first 3 rows):")
    with open(path, newline="", encoding="utf-8") as f:
        for i, row in enumerate(csv.DictReader(f)):
            if i >= 3:
                break
            print(f"  {row['Name']} | DOB: {row['dob']} | Age: {row['Age']}")

if __name__ == "__main__":
    if not CSV_PATH.exists():
        print(f"ERROR: {CSV_PATH} not found.")
        print("Run this script from the patient-intake/ directory:")
        print("  cd patient-intake")
        print("  python3 fix_ages.py")
    else:
        fix_ages(CSV_PATH)