"""
payment.py — Stripe payment routes + patient portal access.
"""
import stripe
import os
import json
import random
import redis as redis_lib
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from models import SessionLocal, Patient, IntakeSession
from dotenv import load_dotenv
from datetime import datetime
from config import settings
from services.sms import (
    send_payment_receipt,
    send_verification_code_email,
    send_reschedule_confirmation,
    send_cancellation_confirmation,
)
from services.mcp_client import call_tool
from services.stripe_mcp import create_payment_link_via_mcp


for env_path in [
    os.path.join(os.path.dirname(__file__), "..", "..", ".env"),
    os.path.join(os.path.dirname(__file__), "..", ".env"),
]:
    if os.path.exists(env_path):
        load_dotenv(env_path)
        break

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
FRONTEND_URL   = os.getenv("FRONTEND_URL", "http://localhost:3000")

redis_client = redis_lib.from_url(settings.redis_url)

router = APIRouter()


class PortalLookupRequest(BaseModel):
    name: str
    dob: str


class CancelAppointmentRequest(BaseModel):
    patient_id: str


class RescheduleConfirmRequest(BaseModel):
    patient_id: str
    doctor: str
    date: str
    time: str
    reason: Optional[str] = None  # None/empty = keep existing reason unchanged


class RequestCodeBody(BaseModel):
    name: str
    dob: str
    method: str = "email"


class VerifyCodeBody(BaseModel):
    lookup_key: str
    code: str


class CreatePortalPaymentLinkRequest(BaseModel):
    patient_id: str


CODE_TTL_SECONDS     = 600
MAX_VERIFY_ATTEMPTS  = 5


def _lookup_key(name: str, dob: str) -> str:
    return f"portal_code:{name.strip().lower()}:{dob.strip()}"


def _mask_email(email: str) -> str:
    if not email or "@" not in email:
        return email
    local, domain = email.split("@")
    return f"{local[:3]}****@{domain}"


def _patient_to_dict(p) -> dict:
    return {
        "patient_id":         p.id,
        "name":               p.name,
        "dob":                p.dob,
        "department":         p.department,
        "appointment_doctor": p.appointment_doctor,
        "appointment_date":   p.appointment_date,
        "appointment_time":   p.appointment_time,
        "payer":              p.payer,
        "copay":              p.copay,
        "payment_status":     getattr(p, "payment_status", "unpaid") or "unpaid",
        "payment_date":       getattr(p, "payment_date", None) or "",
        "reason":             p.reason_for_visit,
        "created_at":         p.created_at.isoformat() if p.created_at else "",
        "appointment_status": getattr(p, "appointment_status", "confirmed") or "confirmed",
    }


@router.post("/portal/lookup")
async def portal_lookup(body: PortalLookupRequest):
    db = SessionLocal()
    try:
        patients = db.query(Patient).filter(
            Patient.name.ilike(f"%{body.name.strip()}%"),
            Patient.dob == body.dob.strip(),
        ).all()
        if not patients:
            raise HTTPException(status_code=404, detail="No records found")
        return {"patients": [_patient_to_dict(p) for p in patients]}
    finally:
        db.close()


@router.post("/portal/request-code")
async def request_portal_code(body: RequestCodeBody):
    if body.method == "phone":
        raise HTTPException(
            status_code=400,
            detail="Text messages aren't available yet — please choose email for now.",
        )
    if body.method != "email":
        raise HTTPException(status_code=400, detail="Unsupported method")

    db = SessionLocal()
    try:
        patients = db.query(Patient).filter(
            Patient.name.ilike(f"%{body.name.strip()}%"),
            Patient.dob == body.dob.strip(),
        ).all()
    finally:
        db.close()

    if not patients:
        raise HTTPException(status_code=404, detail="No records found")

    contact_patient = next((p for p in patients if p.email), None)
    if not contact_patient:
        raise HTTPException(status_code=400, detail="No email on file for this patient")

    code = f"{random.randint(0, 999999):06d}"
    key = _lookup_key(body.name, body.dob)
    redis_client.setex(key, CODE_TTL_SECONDS, json.dumps({"code": code, "attempts": 0}))

    send_verification_code_email(contact_patient.email, code)
    masked = _mask_email(contact_patient.email)

    print(f"[portal] Verification code sent (demo mode — check dev inbox) for {body.name}")
    return {"lookup_key": key, "sent_to": masked}


@router.post("/portal/verify-code")
async def verify_portal_code(body: VerifyCodeBody):
    stored_json = redis_client.get(body.lookup_key)
    if not stored_json:
        raise HTTPException(status_code=400, detail="Code expired — please request a new one")

    stored = json.loads(stored_json)

    if stored["attempts"] >= MAX_VERIFY_ATTEMPTS:
        redis_client.delete(body.lookup_key)
        raise HTTPException(status_code=429, detail="Too many attempts — please request a new code")

    if body.code.strip() != stored["code"]:
        stored["attempts"] += 1
        redis_client.setex(body.lookup_key, CODE_TTL_SECONDS, json.dumps(stored))
        raise HTTPException(status_code=400, detail="Incorrect code")

    redis_client.delete(body.lookup_key)

    _, name_part, dob_part = body.lookup_key.split(":", 2)
    db = SessionLocal()
    try:
        patients = db.query(Patient).filter(
            Patient.name.ilike(f"%{name_part}%"),
            Patient.dob == dob_part,
        ).all()
        return {"patients": [_patient_to_dict(p) for p in patients]}
    finally:
        db.close()


@router.post("/portal/cancel-appointment")
async def cancel_appointment(body: CancelAppointmentRequest):
    db = SessionLocal()
    try:
        patient = db.query(Patient).filter(Patient.id == body.patient_id).first()
        if not patient:
            raise HTTPException(status_code=404, detail="Appointment not found")
        patient.appointment_status = "cancelled"
        db.commit()
        print(f"[portal] Cancelled appointment — patient: {patient.name} (id: {patient.id})")

        send_cancellation_confirmation(
            patient_name=patient.name or "",
            doctor=patient.appointment_doctor or "",
            date=patient.appointment_date or "",
            time=patient.appointment_time or "",
            department=patient.department or "",
        )

        return {"status": "cancelled"}
    finally:
        db.close()


@router.get("/portal/reschedule-slots")
async def reschedule_slots(
    department: str,
    day: Optional[str] = None,
    after_time: Optional[str] = None,
    before_time: Optional[str] = None,
):
    """
    day/after_time/before_time are simple structured filters (not free
    text) — matches a day-of-week or morning/afternoon/evening dropdown
    on the frontend, so this stays fully deterministic with no AI
    interpretation needed, same as the rest of the portal.
    """
    tool_input = {"department": department}
    if day:
        tool_input["day"] = day
    if after_time:
        tool_input["after_time"] = after_time
    if before_time:
        tool_input["before_time"] = before_time

    result = await call_tool("fhir_get_slots", tool_input)
    try:
        parsed = json.loads(result) if isinstance(result, str) else result
    except json.JSONDecodeError:
        parsed = {"slots": []}
    return parsed


@router.post("/portal/reschedule-appointment")
async def reschedule_appointment(body: RescheduleConfirmRequest):
    """
    No identity re-verification and no copay recalculation — patients can
    only reschedule within the SAME department, and copay doesn't vary
    within a department today, so the existing stored copay stays valid.
    reason is optional — if the patient says "same reason" the frontend
    sends nothing and the existing reason_for_visit is left untouched.
    """
    db = SessionLocal()
    try:
        patient = db.query(Patient).filter(Patient.id == body.patient_id).first()
        if not patient:
            raise HTTPException(status_code=404, detail="Appointment not found")
        patient.appointment_doctor = body.doctor
        patient.appointment_date   = body.date
        patient.appointment_time   = body.time
        patient.appointment_status = "confirmed"
        if body.reason:
            patient.reason_for_visit = body.reason
        db.commit()
        print(f"[portal] Rescheduled — patient: {patient.name} -> {body.doctor} on {body.date} at {body.time}")

        send_reschedule_confirmation(
            patient_name=patient.name or "",
            doctor=patient.appointment_doctor or "",
            date=patient.appointment_date or "",
            time=patient.appointment_time or "",
            department=patient.department or "",
            reason=patient.reason_for_visit or "",
        )

        return {"status": "rescheduled"}
    finally:
        db.close()


@router.post("/portal/create-payment-link")
async def create_portal_payment_link(body: CreatePortalPaymentLinkRequest):
    """
    Real Stripe-hosted payment link, same deterministic mechanism as
    intake's payment step — no inline card fields on this page. Patient
    is already fully identified at this point, so patient_id itself is
    used as the reference the webhook resolves against directly (no
    IntakeSession lookup needed for this path).
    """
    db = SessionLocal()
    try:
        patient = db.query(Patient).filter(Patient.id == body.patient_id).first()
    finally:
        db.close()

    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    try:
        copay_cents = int(round(float(patient.copay or "0") * 100))
    except (ValueError, TypeError):
        copay_cents = 0
    if copay_cents <= 0:
        raise HTTPException(status_code=400, detail="No copay due")

    description = (
        f"{patient.department or 'Visit'} copay - "
        f"{patient.appointment_doctor or ''} {patient.appointment_date or ''}".strip()
    )
    link_result = await create_payment_link_via_mcp(copay_cents, description, body.patient_id)
    if "url" not in link_result:
        raise HTTPException(status_code=502, detail=link_result.get("error", "Could not create payment link"))

    return {"url": link_result["url"]}


@router.get("/portal/payment-status/{patient_id}")
async def portal_payment_status(patient_id: str):
    db = SessionLocal()
    try:
        patient = db.query(Patient).filter(Patient.id == patient_id).first()
        if not patient:
            return {"paid": False, "found": False}
        return {"paid": getattr(patient, "payment_status", "") == "paid", "found": True}
    finally:
        db.close()


@router.get("/payment/publishable-key")
async def get_publishable_key():
    return {"publishable_key": os.getenv("STRIPE_PUBLISHABLE_KEY")}


@router.get("/payment/status-by-session/{intake_session_id}")
async def payment_status_by_session(intake_session_id: str):
    db = SessionLocal()
    try:
        session = db.query(IntakeSession).filter(
            IntakeSession.session_id == intake_session_id
        ).first()
        if not session or not session.patient_id:
            return {"paid": False, "found": False}

        patient = db.query(Patient).filter(Patient.id == session.patient_id).first()
        if not patient:
            return {"paid": False, "found": False}

        return {
            "paid": getattr(patient, "payment_status", "") == "paid",
            "found": True,
        }
    finally:
        db.close()


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    payload    = await request.body()
    sig_header = request.headers.get("stripe-signature")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

    print(f"[webhook] Signature header present: {bool(sig_header)}")
    print(f"[webhook] STRIPE_WEBHOOK_SECRET set: {bool(webhook_secret)}")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except Exception as e:
        print(f"[webhook] Verification FAILED: {type(e).__name__}: {e}")
        raise HTTPException(status_code=400, detail="Invalid signature or webhook misconfigured")

    print(f"[webhook] Verified event: {event['type']}")

    if event["type"] in ("checkout.session.completed", "payment_intent.succeeded"):
        obj = event["data"]["object"]
        obj_dict = obj.to_dict() if hasattr(obj, "to_dict") else dict(obj)
        metadata = obj_dict.get("metadata") or {}

        reference_id = metadata.get("session_id")
        print(f"[webhook] metadata reference: {reference_id}")

        if not reference_id:
            print("[webhook] No reference in metadata — cannot resolve patient, skipping")
            return {"status": "ok"}

        db = SessionLocal()
        try:
            # Try resolving as an intake session_id first (chat-flow
            # payments); if that doesn't match anything, treat the same
            # reference as a direct Patient.id instead (portal-flow
            # payments, where patient_id was already known up front).
            patient = None
            intake_session = db.query(IntakeSession).filter(
                IntakeSession.session_id == reference_id
            ).first()
            if intake_session and intake_session.patient_id:
                patient = db.query(Patient).filter(
                    Patient.id == intake_session.patient_id
                ).first()
            else:
                patient = db.query(Patient).filter(Patient.id == reference_id).first()

            if patient:
                patient.payment_status = "paid"
                patient.payment_date = datetime.now().strftime("%B %d, %Y at %I:%M %p")
                db.commit()
                print(f"[webhook] Marked paid — patient: {patient.name} (id: {patient.id})")

                send_payment_receipt(
                    patient_name=patient.name or "",
                    doctor=patient.appointment_doctor or "",
                    date=patient.appointment_date or "",
                    time=patient.appointment_time or "",
                    department=patient.department or "",
                    amount=patient.copay or "0",
                    payment_date=patient.payment_date,
                )
            else:
                print(f"[webhook] Could not resolve reference to any patient: {reference_id}")
        finally:
            db.close()

    return {"status": "ok"}