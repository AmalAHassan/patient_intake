"""
payment.py — Stripe payment routes.
"""
import stripe
import os
import json
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from models import SessionLocal, Patient, IntakeSession
from dotenv import load_dotenv
from datetime import datetime
from services.sms import send_payment_receipt
from services.mcp_client import call_tool


for env_path in [
    os.path.join(os.path.dirname(__file__), "..", "..", ".env"),
    os.path.join(os.path.dirname(__file__), "..", ".env"),
]:
    if os.path.exists(env_path):
        load_dotenv(env_path, override=True)
        break

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
FRONTEND_URL   = os.getenv("FRONTEND_URL", "http://localhost:3000")

router = APIRouter()


class CreateCheckoutRequest(BaseModel):
    patient_id: str
    amount_dollars: float
    patient_name: str
    doctor: Optional[str] = ""
    date: Optional[str] = ""
    description: Optional[str] = "Copay payment"


class ConfirmCheckoutRequest(BaseModel):
    patient_id: str
    session_id: str


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


@router.post("/payment/create-checkout-session")
async def create_checkout_session(body: CreateCheckoutRequest):
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": f"Copay — {body.doctor} {body.date}".strip(" —"),
                    },
                    "unit_amount": int(round(body.amount_dollars * 100)),
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=(
                f"{FRONTEND_URL}/intake?payment=success"
                f"&patient_id={body.patient_id}"
                f"&session_id={{CHECKOUT_SESSION_ID}}"
            ),
            cancel_url=f"{FRONTEND_URL}/intake?payment=cancelled",
            metadata={"patient_id": body.patient_id},
        )
        return {"checkout_url": session.url}
    except Exception as e:
        print(f"[stripe] Failed to create checkout session: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/payment/confirm-checkout")
async def confirm_checkout(body: ConfirmCheckoutRequest):
    try:
        session = stripe.checkout.Session.retrieve(body.session_id)

        if session.payment_status != "paid":
            return {"status": session.payment_status}

        db = SessionLocal()
        try:
            patient = db.query(Patient).filter(
                Patient.id == body.patient_id
            ).first()
            if patient:
                payment_date = datetime.now().strftime("%B %d, %Y at %I:%M %p")
                patient.payment_status    = "paid"
                patient.payment_intent_id = session.payment_intent
                patient.payment_date      = payment_date
                db.commit()
                print(f"[stripe] Payment confirmed — patient: {patient.name} — session: {body.session_id}")

                send_payment_receipt(
                    patient_name=patient.name or "",
                    doctor=patient.appointment_doctor or "",
                    date=patient.appointment_date or "",
                    time=patient.appointment_time or "",
                    department=patient.department or "",
                    amount=patient.copay or "0",
                    payment_date=payment_date,
                )
        finally:
            db.close()

        return {"status": "paid"}
    except Exception as e:
        print(f"[stripe] Confirm checkout failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))


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

        return {
            "patients": [
                {
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
                for p in patients
            ]
        }
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
        return {"status": "cancelled"}
    finally:
        db.close()


@router.get("/portal/reschedule-slots")
async def reschedule_slots(department: str):
    """Reuses the same fhir_get_slots logic the intake chat agent uses,
    so reschedule shows real, current availability — not a guess."""
    result = await call_tool("fhir_get_slots", {"department": department})
    try:
        parsed = json.loads(result) if isinstance(result, str) else result
    except json.JSONDecodeError:
        parsed = {"slots": []}
    return parsed


@router.post("/portal/reschedule-appointment")
async def reschedule_appointment(body: RescheduleConfirmRequest):
    db = SessionLocal()
    try:
        patient = db.query(Patient).filter(Patient.id == body.patient_id).first()
        if not patient:
            raise HTTPException(status_code=404, detail="Appointment not found")
        patient.appointment_doctor = body.doctor
        patient.appointment_date   = body.date
        patient.appointment_time   = body.time
        patient.appointment_status = "confirmed"
        db.commit()
        print(f"[portal] Rescheduled — patient: {patient.name} -> {body.doctor} on {body.date} at {body.time}")
        return {"status": "rescheduled"}
    finally:
        db.close()


@router.get("/payment/publishable-key")
async def get_publishable_key():
    return {"publishable_key": os.getenv("STRIPE_PUBLISHABLE_KEY")}


@router.get("/payment/status-by-session/{intake_session_id}")
async def payment_status_by_session(intake_session_id: str):
    """
    Polled by the ORIGINAL intake chat tab (not the Stripe tab) to detect
    when payment succeeds, so it can show a confirmation message without
    needing the patient to do anything else. Resolves our own
    intake_session_id -> the patient row created for that session -> its
    current payment_status.
    """
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
        # Broadened from (ValueError, SignatureVerificationError) — a
        # None/missing secret raises a raw AttributeError from inside
        # stripe's own library (calling .encode() on None) BEFORE it ever
        # gets to a proper signature-verification error, which slipped
        # past the narrower except clause and crashed as an unhandled 500
        # instead of a clean 400.
        print(f"[webhook] Verification FAILED: {type(e).__name__}: {e}")
        raise HTTPException(status_code=400, detail="Invalid signature or webhook misconfigured")

    print(f"[webhook] Verified event: {event['type']}")

    if event["type"] in ("checkout.session.completed", "payment_intent.succeeded"):
        obj = event["data"]["object"]

        # obj is a Stripe SDK object, not a plain dict — chaining .get()
        # calls directly on it can trigger its custom __getattr__ lookup
        # and raise AttributeError. Convert to a real dict first, then
        # .get() safely on that.
        obj_dict = obj.to_dict() if hasattr(obj, "to_dict") else dict(obj)
        metadata = obj_dict.get("metadata") or {}

        # Our Payment Link attaches metadata.session_id (our OWN intake
        # session ID) — NOT patient_id, since patient_id doesn't exist
        # yet at the moment the payment link is created (it's generated
        # afterward, once intake completes). Resolve session -> patient
        # here instead.
        intake_session_id = metadata.get("session_id")
        print(f"[webhook] metadata.session_id: {intake_session_id}")

        if not intake_session_id:
            print("[webhook] No session_id in metadata — cannot resolve patient, skipping")
            return {"status": "ok"}

        db = SessionLocal()
        try:
            intake_session = db.query(IntakeSession).filter(
                IntakeSession.session_id == intake_session_id
            ).first()

            if not intake_session or not intake_session.patient_id:
                print(f"[webhook] No matching IntakeSession/patient_id for session_id: {intake_session_id}")
                return {"status": "ok"}

            patient = db.query(Patient).filter(
                Patient.id == intake_session.patient_id
            ).first()

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
                print(f"[webhook] IntakeSession found but Patient row missing for id: {intake_session.patient_id}")
        finally:
            db.close()

    return {"status": "ok"}