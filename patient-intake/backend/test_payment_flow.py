"""
test_payment_flow.py — Bypasses the entire intake chat to directly test
the payment-tab behavior (paid / closed-without-paying / timeout).

Creates a real IntakeSession + Patient row in your actual database (same
tables the real chat flow uses), then calls the real
create_payment_link_via_mcp() to get a genuine Stripe payment link with
correct metadata — everything downstream (webhook, portal, frontend
polling) behaves exactly as it would from a real conversation.

Run from inside backend/, with your venv active:
    python test_payment_flow.py

Then open your frontend and manually navigate to intake.tsx's polling
by pasting the printed session_id into your browser console:

    (this requires the chat to already be in "complete" status with a
    payment_url — see the note printed at the end of this script for
    the actual quickest way to trigger polling using this fake data)
"""
import asyncio
import uuid
from datetime import datetime
from models import SessionLocal, IntakeSession, Patient
from services.stripe_mcp import create_payment_link_via_mcp


async def main():
    session_id = str(uuid.uuid4())
    patient_id = str(uuid.uuid4())

    db = SessionLocal()
    try:
        session = IntakeSession(session_id=session_id)
        session.patient_id = patient_id
        session.status = "completed"
        db.add(session)

        patient = Patient(
            id=patient_id,
            fhir_id=patient_id,
            name="Test Patient",
            dob="01/01/1990",
            phone="555-000-1111",
            email="test@example.com",
            insurance_id="TEST-001",
            payer="Blue Cross",
            copay="25",
            department="Family Medicine",
            reason_for_visit="test payment flow",
            appointment_doctor="Dr. Patel",
            appointment_date="Test Date",
            appointment_time="Test Time",
            payment_status="unpaid",
        )
        db.add(patient)
        db.commit()
        print(f"[seed] Created IntakeSession: {session_id}")
        print(f"[seed] Created Patient: {patient_id}")
    finally:
        db.close()

    link_result = await create_payment_link_via_mcp(
        copay_cents=2500,
        description="Test Payment Flow",
        session_id=session_id,
    )

    if "url" in link_result:
        print(f"\n[seed] Real payment link: {link_result['url']}")
        print(f"\nTo test:")
        print(f"1. Open this link in a new tab and either pay with the test card,")
        print(f"   or just close the tab without paying.")
        print(f"2. Check status manually:")
        print(f"   curl http://localhost:8000/payment/status-by-session/{session_id}")
        print(f"3. Or check the portal — look up 'Test Patient' / DOB '01/01/1990'.")
    else:
        print(f"[seed] Failed to create payment link: {link_result.get('error')}")


if __name__ == "__main__":
    asyncio.run(main())