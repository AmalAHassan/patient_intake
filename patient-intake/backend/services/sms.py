import os
import httpx
from dotenv import load_dotenv

for env_path in [
    os.path.join(os.path.dirname(__file__), "..", "..", ".env"),
    os.path.join(os.path.dirname(__file__), "..", ".env"),
]:
    if os.path.exists(env_path):
        load_dotenv(env_path)
        break

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
FROM_EMAIL     = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev")
TO_EMAIL       = os.getenv("DEV_NOTIFY_EMAIL", "amal@ledelsea.com")

print("[sms] RESEND_API_KEY set:", bool(RESEND_API_KEY))


def _send(subject: str, body: str) -> bool:
    if not RESEND_API_KEY:
        print("[sms] RESEND_API_KEY not set — skipping email")
        return False
    try:
        response = httpx.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": FROM_EMAIL,
                "to": [TO_EMAIL],
                "subject": subject,
                "text": body,
            },
            timeout=10.0,
        )
        if response.status_code == 200 or response.status_code == 201:
            print(f"[sms] Email sent: {subject}")
            return True
        else:
            print(f"[sms] Email failed: {response.status_code} {response.text}")
            return False
    except Exception as e:
        print(f"[sms] Email failed: {e}")
        return False


def send_appointment_confirmation(
    to_number: str,
    patient_name: str,
    doctor: str,
    date: str,
    time: str,
    department: str,
) -> bool:
    return _send(
        subject=f"Appointment Confirmed — {patient_name} with {doctor} on {date}",
        body=(
            f"Hi {patient_name},\n\n"
            f"Your appointment has been confirmed!\n\n"
            f"Doctor:      {doctor}\n"
            f"Department:  {department}\n"
            f"Date:        {date}\n"
            f"Time:        {time}\n\n"
            f"Please arrive 10 minutes early and bring your insurance card and a valid photo ID.\n\n"
            f"To reschedule or cancel, please call us directly.\n\n"
            f"— Ledelsea Health"
        ),
    )


def send_payment_receipt(
    patient_name: str,
    doctor: str,
    date: str,
    time: str,
    department: str,
    amount: str,
    payment_date: str,
) -> bool:
    return _send(
        subject=f"Payment Receipt — ${amount} for {patient_name}",
        body=(
            f"Hi {patient_name},\n\n"
            f"Payment received — thank you!\n\n"
            f"Receipt\n"
            f"-------\n"
            f"Amount paid:   ${amount}\n"
            f"Date paid:     {payment_date}\n"
            f"Doctor:        {doctor}\n"
            f"Department:    {department}\n"
            f"Appointment:   {date} at {time}\n\n"
            f"Your copay has been processed. See you at your appointment!\n\n"
            f"— Ledelsea Health"
        ),
    )


def send_verification_code_email(patient_email: str, code: str) -> bool:
    """
    Sends the patient portal verification code. Like every other email in
    this demo, this currently goes to DEV_NOTIFY_EMAIL regardless of the
    real patient_email passed in — intentional for now, per the plan to
    connect real patient email/phone once there's a real stakeholder
    using this in production.
    """
    return _send(
        subject="Your Ledelsea Patient Portal verification code",
        body=(
            f"Your verification code is: {code}\n\n"
            f"This code expires in 10 minutes. If you didn't request "
            f"this, you can safely ignore this email.\n\n"
            f"— Ledelsea Health"
        ),
    )


def send_reschedule_confirmation(
    patient_name: str,
    doctor: str,
    date: str,
    time: str,
    department: str,
    reason: str = "",
) -> bool:
    return _send(
        subject=f"Appointment Rescheduled — {patient_name} with {doctor} on {date}",
        body=(
            f"Hi {patient_name},\n\n"
            f"Your appointment has been rescheduled.\n\n"
            f"New details\n"
            f"-----------\n"
            f"Doctor:      {doctor}\n"
            f"Department:  {department}\n"
            f"Date:        {date}\n"
            f"Time:        {time}\n"
            + (f"Reason:      {reason}\n" if reason else "")
            + "\nPlease arrive 10 minutes early and bring your insurance card and a valid photo ID.\n\n"
            f"— Ledelsea Health"
        ),
    )


def send_cancellation_confirmation(
    patient_name: str,
    doctor: str,
    date: str,
    time: str,
    department: str,
) -> bool:
    return _send(
        subject=f"Appointment Cancelled — {patient_name}",
        body=(
            f"Hi {patient_name},\n\n"
            f"This confirms your appointment has been cancelled.\n\n"
            f"Cancelled appointment\n"
            f"----------------------\n"
            f"Doctor:      {doctor}\n"
            f"Department:  {department}\n"
            f"Date:        {date}\n"
            f"Time:        {time}\n\n"
            f"If this wasn't you, or you'd like to book a new appointment, "
            f"please visit the patient portal or contact us directly.\n\n"
            f"— Ledelsea Health"
        ),
    )