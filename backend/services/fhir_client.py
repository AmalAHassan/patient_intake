import os
import requests
from datetime import datetime

# Import settings safely — works whether called from backend/ or a subprocess
try:
    from config import settings
    FHIR_BASE_URL = settings.fhir_base_url
except Exception:
    FHIR_BASE_URL = os.getenv("FHIR_BASE_URL", "http://localhost:8080/fhir")


def create_patient(data: dict) -> str:
    """Create a FHIR Patient resource and return the patient ID."""
    telecom = []
    if data.get("phone"):
        telecom.append({"system": "phone", "value": data["phone"]})
    if data.get("email"):
        telecom.append({"system": "email", "value": data["email"]})

    def _format_dob(dob: str) -> str:
        try:
            return datetime.strptime(dob, "%m/%d/%Y").strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            return dob

    patient_resource = {
        "resourceType": "Patient",
        "name": [{"text": data.get("name", "")}],
        "birthDate": _format_dob(data.get("dob", "")),
        "telecom": telecom,
        "contact": [{"telecom": telecom}],
        "extension": [
            {
                "url": "http://example.com/insurance",
                "valueString": f"{data.get('insurance_id', '')} - {data.get('payer', '')}",
            },
            {
                "url": "http://example.com/reason_for_visit",
                "valueString": data.get("reason", ""),
            },
            {
                "url": "http://example.com/department",
                "valueString": data.get("department", ""),
            },
            {
                "url": "http://example.com/appointment",
                "valueString": f"{data.get('appointment_doctor', '')} — {data.get('appointment_date', '')} at {data.get('appointment_time', '')}",
            },
        ],
    }

    try:
        response = requests.post(
            f"{FHIR_BASE_URL}/Patient",
            json=patient_resource,
            timeout=10,
        )
        response.raise_for_status()
        created_resource = response.json()
        fhir_id = created_resource.get("id", "")
        print(f"[fhir_client] Patient created: {fhir_id}")
        return fhir_id
    except requests.RequestException as e:
        print(f"[fhir_client] Error creating patient: {e}")
        return ""


def get_patient(patient_id: str) -> dict:
    """Get a FHIR Patient resource by ID."""
    try:
        response = requests.get(
            f"{FHIR_BASE_URL}/Patient/{patient_id}",
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"[fhir_client] Error fetching patient: {e}")
        return {}