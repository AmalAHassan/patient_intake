import requests
from datetime import datetime
#from config import settings


def create_patient(data: dict) -> str:
    """Create a FHIR Patient resource and return the patient ID."""
    telecom = []
    if data.get("phone"):
        telecom.append({"system": "phone", "value": data["phone"]})
    if data.get("email"):
        telecom.append({"system": "email", "value": data["email"]})
        
    def _format_dob(dob: str) -> str:
        """Convert MM/DD/YYYY to YYYY-MM-DD for FHIR R4."""
        try:
            return datetime.strptime(dob, "%m/%d/%Y").strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            return dob  # pass through if already formatted or empty

    patient_resource = {
        "resourceType": "Patient",
        "name": [{"text": data.get("name", "")}],
        "birthDate": _format_dob(data.get("dob", "")),
        "telecom": telecom,
        "contact": [
            {
                "telecom": telecom,
            }
        ],
        "extension": [
            {
                "url": "http://example.com/insurance",
                "valueString": f"{data.get('insurance_id')} - {data.get('payer')}",
            },
            {
                "url": "http://example.com/reason_for_visit",
                "valueString": data.get("reason", ""),
            },
        ],
    }

    try:
        response = requests.post(
            f"{settings.fhir_base_url}/Patient",
            json=patient_resource,
            timeout=10,
        )
        response.raise_for_status()
        created_resource = response.json()
        return created_resource.get("id", "")
    except requests.RequestException as e:
        print(f"Error creating FHIR patient: {e}")
        return ""


def get_patient(patient_id: str) -> dict:
    """Get a FHIR Patient resource by ID."""
    try:
        response = requests.get(
            f"{settings.fhir_base_url}/Patient/{patient_id}",
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error fetching FHIR patient: {e}")
        return {}
