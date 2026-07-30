"""
view_patients_table.py — Pulls all Patient records from your local HAPI
FHIR server and displays them as a clean table instead of raw JSON.
"""
import sys
import requests
import pandas as pd

FHIR_URL = "http://localhost:8080/fhir/Patient?_count=100"


def extract_extension_value(patient: dict, url_suffix: str) -> str:
    """Custom fields were stored as generic FHIR extensions
    (url + valueString pairs) rather than native Patient fields."""
    for ext in patient.get("extension", []):
        if ext.get("url", "").endswith(url_suffix):
            return ext.get("valueString", "")
    return ""


def flatten_patient(entry: dict) -> dict:
    p = entry["resource"]

    name = ""
    if p.get("name"):
        name_obj = p["name"][0]
        name = name_obj.get("text") or " ".join(
            name_obj.get("given", []) + [name_obj.get("family", "")]
        )

    phone = ""
    email = ""
    for telecom in p.get("telecom", []):
        if telecom.get("system") == "phone":
            phone = telecom.get("value", "")
        elif telecom.get("system") == "email":
            email = telecom.get("value", "")

    return {
        "FHIR ID":        p.get("id", ""),
        "Name":           name,
        "DOB":            p.get("birthDate", ""),
        "Phone":          phone,
        "Email":          email,
        "Insurance":      extract_extension_value(p, "insurance"),
        "Department":     extract_extension_value(p, "department"),
        "Reason":         extract_extension_value(p, "reason_for_visit"),
        "Appointment":    extract_extension_value(p, "appointment"),
        "Last Updated":   p.get("meta", {}).get("lastUpdated", ""),
    }


def main():
    try:
        response = requests.get(FHIR_URL, timeout=10)
        response.raise_for_status()
    except requests.exceptions.ConnectionError:
        print(f"Could not reach {FHIR_URL} — is your hapi-fhir Docker container running?")
        sys.exit(1)

    bundle = response.json()
    entries = bundle.get("entry", [])

    if not entries:
        print("No patients found.")
        return

    rows = [flatten_patient(e) for e in entries]
    df = pd.DataFrame(rows)

    if len(sys.argv) > 2 and sys.argv[1] == "--csv":
        df.to_csv(sys.argv[2], index=False)
        print(f"Saved {len(df)} patients to {sys.argv[2]}")
    else:
        print(f"\n{len(df)} patient(s) found:\n")
        print(df.to_string(index=False))


if __name__ == "__main__":
    main()
    