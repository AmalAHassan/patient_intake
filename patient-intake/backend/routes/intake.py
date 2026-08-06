from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
import uuid
import json
import traceback
from services import fhir_client
from services.sms import send_appointment_confirmation
from services.claude import _send_crisis_alert
from services.mcp_client import call_tool
from models import SessionLocal, IntakeSession, Patient
from graph import graph, resolve_payment

router = APIRouter()


class MessageRequest(BaseModel):
    session_id: str
    message: str


class StartRequest(BaseModel):
    name: Optional[str] = None


class StartResponse(BaseModel):
    session_id: str
    message: str


class QuickSlotsRequest(BaseModel):
    session_id: str
    day: Optional[str] = None
    after_time: Optional[str] = None
    before_time: Optional[str] = None


def _config_for(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}


def _default_state(session_id: str, messages: list) -> dict:
    return {
        "messages": messages,
        "current_agent": "identity",
        "return_to": None,
        "slots_ever_called": False,
        "routing_turns_without_redirect": 0,
        "last_routing_reply": "",
        "department": None,
        "session_id": session_id,
        "lookup_count": 0,
        "just_redirected": False,
        "status": None,
        "final_reply": None,
        "data": None,
        "payment": None,
        "payment_url": None,
    }


async def _get_current_messages(session_id: str) -> list:
    """
    The messages channel has no accumulating reducer (nodes manage the
    full list themselves and return it complete each time), so a bare
    partial update would REPLACE history rather than append to it. Fetch
    the current persisted list first, then append the new patient
    message to the FULL list before invoking.
    """
    snapshot = await graph.aget_state(_config_for(session_id))
    if snapshot and snapshot.values:
        return snapshot.values.get("messages", [])
    return []


@router.post("/start", response_model=StartResponse)
async def start_intake(body: StartRequest = StartRequest()):
    session_id = str(uuid.uuid4())

    db = SessionLocal()
    session = IntakeSession(session_id=session_id)
    db.add(session)
    db.commit()
    db.close()

    initial_state = _default_state(session_id, [{"role": "user", "content": "begin"}])
    result = await graph.ainvoke(initial_state, config=_config_for(session_id))

    return {"session_id": session_id, "message": result.get("final_reply", "")}


@router.post("/message")
async def send_message(request: MessageRequest, req: Request):
    try:
        client_ip = req.client.host if req.client else "unknown"
        config = _config_for(request.session_id)

        current_messages = await _get_current_messages(request.session_id)
        new_messages = current_messages + [{"role": "user", "content": request.message}]

        result = await graph.ainvoke({"messages": new_messages}, config=config)
        status = result.get("status")
        final_reply = result.get("final_reply") or ""
        current_agent = result.get("current_agent", "")

        if status == "emergency_redirect":
            text_lower = final_reply.lower()
            is_crisis = any(
                kw in text_lower
                for kw in ["988", "suicidal", "self-harm", "tired of life", "can't do this"]
            )
            messages = result.get("messages", [])
            reason = messages[-2]["content"] if len(messages) >= 2 else "unknown"
            await _send_crisis_alert(
                session_id=request.session_id,
                alert_type="mental_health_crisis" if is_crisis else "medical_emergency",
                reason=reason,
                client_ip=client_ip,
            )
            return {"reply": final_reply, "status": "emergency_redirect", "data": None, "current_agent": current_agent}

        if status == "staff_requested":
            return {"reply": final_reply, "status": "staff_requested", "data": None, "current_agent": current_agent}

        if status == "ended":
            return {"reply": final_reply, "status": "ended", "data": None, "current_agent": current_agent}

        if status == "complete" and result.get("data"):
            collected_data = result["data"]
            patient_id = str(uuid.uuid4())

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
                    name=collected_data.get("name"),
                    dob=collected_data.get("dob"),
                    phone=collected_data.get("phone"),
                    email=collected_data.get("email"),
                    insurance_id=collected_data.get("insurance_id"),
                    payer=collected_data.get("payer"),
                    copay=collected_data.get("copay"),
                    department=collected_data.get("department"),
                    reason_for_visit=collected_data.get("reason"),
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

            payment_result = await resolve_payment(result)
            payment_url = payment_result.get("payment_url")
            payment_choice = payment_result.get("payment", result.get("payment", "later"))

            send_appointment_confirmation(
                to_number=collected_data.get("phone", ""),
                patient_name=collected_data.get("name", ""),
                doctor=collected_data.get("appointment_doctor", ""),
                date=collected_data.get("appointment_date", ""),
                time=collected_data.get("appointment_time", ""),
                department=collected_data.get("department", ""),
            )

            return {
                "reply": final_reply,
                "status": "complete",
                "data": collected_data,
                "patient_id": patient_id,
                "fhir_id": fhir_id,
                "payment": payment_choice,
                "payment_url": payment_url,
                "current_agent": current_agent,
            }

        return {
            "reply": final_reply,
            "status": "collecting",
            "data": result.get("data"),
            "current_agent": current_agent,
        }

    except Exception as e:
        print(f"[intake] Unhandled error: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


def _format_slots_message(slots: list) -> str:
    if not slots:
        return "I don't see any slots matching that filter right now."
    lines = [
        f"{i+1}. {s.get('doctor', '')} — {s.get('date', '')} at {s.get('time', '')}"
        for i, s in enumerate(slots[:5])
    ]
    return "\n".join(lines)

@router.post("/quick-slots")
async def quick_slots(request: QuickSlotsRequest):
    """
    Fetches slots directly via fhir_get_slots — bypassing the model
    entirely for this one action (no extra LLM call, no token cost, fully
    deterministic — matches the portal's dropdown filters). The result
    still gets woven into the graph's persisted conversation history via
    aupdate_state(), so if the patient goes back to typing in chat
    afterward, the model sees a coherent history, as if the scheduling
    agent itself had just shown these slots.
    """
    config = _config_for(request.session_id)
    snapshot = await graph.aget_state(config)
    if not snapshot or not snapshot.values:
        raise HTTPException(status_code=404, detail="Session not found")

    department = snapshot.values.get("department")
    if not department:
        raise HTTPException(
            status_code=400,
            detail="Department not yet confirmed — please continue the conversation first.",
        )

    tool_input = {"department": department}
    if request.day:
        tool_input["day"] = request.day
    if request.after_time:
        tool_input["after_time"] = request.after_time
    if request.before_time:
        tool_input["before_time"] = request.before_time

    raw_result = await call_tool("fhir_get_slots", tool_input)
    try:
        parsed = json.loads(raw_result) if isinstance(raw_result, str) else raw_result
    except json.JSONDecodeError:
        parsed = {"slots": []}

    reply_text = _format_slots_message(parsed.get("slots", []))

    updated_messages = snapshot.values["messages"] + [
        {"role": "assistant", "content": reply_text}
    ]
    await graph.aupdate_state(
        config,
        {
            "messages": updated_messages,
            "slots_ever_called": True,
        },
    )

    return {"reply": reply_text}


@router.get("/session/{session_id}")
async def get_session(session_id: str):
    """
    Retrieve completed intake data for a session — reads from the graph's
    own checkpointer, falling back to Postgres for older/expired sessions.
    """
    snapshot = await graph.aget_state(_config_for(session_id))
    if snapshot and snapshot.values and snapshot.values.get("data"):
        return {"session_id": session_id, "status": "complete", "data": snapshot.values["data"]}

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