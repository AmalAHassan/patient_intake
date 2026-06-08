import os
import re
import pandas as pd

_df = None

CSV_FILENAME = "patients_enriched.csv"


def _normalize_phone(value) -> str:
    if value is None:
        return ""
    digits = re.sub(r"\D", "", str(value))
    return digits[-10:] if len(digits) >= 10 else digits


def load_patients():
    global _df
    path = os.path.join(os.path.dirname(__file__), "..", "data", CSV_FILENAME)
    if os.path.exists(path):
        df = pd.read_csv(path, dtype=str).fillna("")
        df["_name_lower"] = df["Name"].str.lower().str.strip()
        df["_phone_norm"] = df["phone"].map(_normalize_phone)
        df["_dob_norm"] = df["dob"].str.strip()
        _df = df
        print(f"Loaded {len(_df)} patients from dataset")
    else:
        _df = pd.DataFrame()
        print(f"Patient dataset not found at {path}; lookup disabled")


def find_patient(name: str = None, dob: str = None, phone: str = None) -> dict | None:
    if _df is None or _df.empty:
        return None
    df = _df

    if name:
        needle = name.lower().strip()
        df = df[df["_name_lower"].str.contains(re.escape(needle), na=False)]

    if dob and not df.empty:
        df = df[df["_dob_norm"] == dob.strip()]

    if phone and not df.empty:
        df = df[df["_phone_norm"] == _normalize_phone(phone)]

    if df.empty:
        return None

    row = df.iloc[0].to_dict()
    return {
        "name": str(row.get("Name", "")).title(),
        "dob": row.get("dob", ""),
        "phone": row.get("phone", ""),
        "email": row.get("email", ""),
        "address": row.get("address", ""),
        "member_id": row.get("member_id", ""),
        "insurance_provider": row.get("Insurance Provider", ""),
        "match_count": int(len(df)),
    }
