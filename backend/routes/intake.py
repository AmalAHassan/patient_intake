from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
import uuid
import traceback
from services import claude, fhir_client
from models import SessionLocal, IntakeSession, Patient
from services.claude import get_session_data

router = APIRouter()


class MessageRequest(BaseModel):
    session_id: str
    message: str


class StartRequest(BaseModel):
    name: Optional[str] = None


class StartResponse(BaseModel):
    session_id: str
    message: str


@router.post("/start", response_model=StartResponse)
async def start_intake(body: StartRequest = StartRequest()):
    session_id = str(uuid.uuid4())

    db = SessionLocal()
    session = IntakeSession(session_id=session_id)
    db.add(session)
    db.commit()
    db.close()

    response = await claude.chat(session_id, "__start__")
    return {"session_id": session_id, "message": response["reply"]}


@router.post("/message")
async def send_message(request: MessageRequest, req: Request):
    try:
        client_ip = req.client.host if req.client else "unknown"
        response = await claude.chat(request.session_id, request.message, client_ip=client_ip)

        if response["status"] == "complete" and response["data"]:
            collected_data = response["data"]
            patient_id = str(uuid.uuid4())

            # FHIR write — non-blocking, patient record saved in DB regardless
            fhir_id = patient_id
            try:
                fhir_id = fhir_client.create_patient(collected_data) or patient_id
            except Exception as fhir_err:
                print(f"[intake] FHIR write failed (non-fatal): {fhir_err}")

            db = SessionLocal()
            try:
                patient = Patient(
                    id=patient_id,
                    fhir_id=fhir_id,
                    # Identity
                    name=collected_data.get("name"),
                    dob=collected_data.get("dob"),
                    phone=collected_data.get("phone"),
                    email=collected_data.get("email"),
                    # Insurance
                    insurance_id=collected_data.get("insurance_id"),
                    payer=collected_data.get("payer"),
                    copay=collected_data.get("copay"),
                    # Visit
                    department=collected_data.get("department"),
                    reason_for_visit=collected_data.get("reason"),
                    # Appointment
                    appointment_doctor=collected_data.get("appointment_doctor"),
                    appointment_date=collected_data.get("appointment_date"),
                    appointment_time=collected_data.get("appointment_time"),
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
            except Exception as db_err:
                print(f"[intake] DB write failed: {db_err}")
                db.rollback()
            finally:
                db.close()

            return {
                "reply": response["reply"],
                "status": "complete",
                "data": collected_data,
                "patient_id": patient_id,
                "fhir_id": fhir_id,
            }

        return {
            "reply": response["reply"],
            "status": response["status"],
            "data": response.get("data"),
        }

    except Exception as e:
        print(f"[intake] Unhandled error: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/session/{session_id}")
async def get_session(session_id: str):
    """
    Retrieve completed intake data for a session.
    Used by the frontend to show a summary after intake completes.
    """
    # Check Redis first (fast, works during active session)
    data = await get_session_data(session_id)
    if data:
        return {"session_id": session_id, "status": "complete", "data": data}

    # Fall back to PostgreSQL (works after Redis TTL expires)
    db = SessionLocal()
    try:
        session = db.query(IntakeSession).filter(
            IntakeSession.session_id == session_id
        ).first()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return {
            "session_id": session_id,
            "status": session.status,
            "data": session.collected_data or {},
        }
    finally:
        db.close()