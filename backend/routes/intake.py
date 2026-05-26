from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import uuid
from services import claude, fhir_client
from models import SessionLocal, IntakeSession, Patient

router = APIRouter()


class MessageRequest(BaseModel):
    session_id: str
    message: str


class StartResponse(BaseModel):
    session_id: str
    message: str


@router.post("/start", response_model=StartResponse)
async def start_intake():
    """Start a new intake session."""
    session_id = str(uuid.uuid4())

    db = SessionLocal()
    session = IntakeSession(session_id=session_id)
    db.add(session)
    db.commit()
    db.close()

    initial_message = "Hello! I'm your patient intake assistant. Let's get started. What is your full name?"

    return {"session_id": session_id, "message": initial_message}


@router.post("/message")
async def send_message(request: MessageRequest):
    """Process a user message in an intake session."""
    try:
        response = await claude.chat(request.session_id, request.message)

        if response["status"] == "complete" and response["data"]:
            collected_data = response["data"]
            patient_id = str(uuid.uuid4())
            fhir_id = fhir_client.create_patient(collected_data)

            db = SessionLocal()
            patient = Patient(
                id=patient_id,
                fhir_id=fhir_id or patient_id,
                name=collected_data.get("name"),
                dob=collected_data.get("dob"),
                phone=collected_data.get("phone"),
                email=collected_data.get("email"),
                insurance_id=collected_data.get("insurance_id"),
                payer=collected_data.get("payer"),
                reason_for_visit=collected_data.get("reason"),
            )
            db.add(patient)

            session = db.query(IntakeSession).filter(
                IntakeSession.session_id == request.session_id
            ).first()
            if session:
                session.patient_id = patient_id
                session.collected_data = collected_data
                session.status = "completed"

            db.commit()
            db.close()

            return {
                "reply": response["reply"],
                "status": "complete",
                "data": collected_data,
                "patient_id": patient_id,
                "fhir_id": fhir_id or patient_id,
            }

        return {
            "reply": response["reply"],
            "status": response["status"],
            "data": response.get("data"),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
