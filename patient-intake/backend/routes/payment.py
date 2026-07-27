"""
payment.py — Stripe payment routes.
Uses Stripe Checkout — patients are redirected to a Stripe-hosted payment
page, so raw card data and the payment UI never touch this app at all.
"""
import stripe
import os
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from models import SessionLocal, Patient
from dotenv import load_dotenv
from datetime import datetime
from services.sms import send_payment_receipt


for env_path in [
    os.path.join(os.path.dirname(__file__), "..", "..", ".env"),
    os.path.join(os.path.dirname(__file__), "..", ".env"),
]:
    if os.path.exists(env_path):
        load_dotenv(env_path)
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
            # {CHECKOUT_SESSION_ID} is a literal Stripe placeholder — Stripe
            # fills it in when redirecting back, so the frontend can pass it
            # to /payment/confirm-checkout to verify the payment actually
            # succeeded (never trust the redirect alone).
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
                }
                for p in patients
            ]
        }
    finally:
        db.close()


@router.get("/payment/publishable-key")
async def get_publishable_key():
    return {"publishable_key": os.getenv("STRIPE_PUBLISHABLE_KEY")}

@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    payload    = await request.body()
    sig_header = request.headers.get("stripe-signature")
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, os.getenv("STRIPE_WEBHOOK_SECRET")
        )
    except (ValueError, stripe.error.SignatureVerificationError):
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event["type"] in ("checkout.session.completed", "payment_intent.succeeded"):
        obj = event["data"]["object"]
        patient_id = obj.get("metadata", {}).get("patient_id")
        if patient_id:
            db = SessionLocal()
            try:
                patient = db.query(Patient).filter(Patient.id == patient_id).first()
                if patient:
                    patient.payment_status = "paid"
                    patient.payment_date = datetime.now().strftime("%B %d, %Y at %I:%M %p")
                    db.commit()
                    send_payment_receipt(
                        patient_name=patient.name or "",
                        doctor=patient.appointment_doctor or "",
                        date=patient.appointment_date or "",
                        time=patient.appointment_time or "",
                        department=patient.department or "",
                        amount=patient.copay or "0",
                        payment_date=patient.payment_date,
                    )
            finally:
                db.close()

    return {"status": "ok"}