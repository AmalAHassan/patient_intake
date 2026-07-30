from sqlalchemy import Column, String, DateTime, JSON, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from config import settings
import uuid

Base = declarative_base()
engine = create_engine(settings.database_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Patient(Base):
    __tablename__ = "patients"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    fhir_id = Column(String, index=True)

    # Identity
    name = Column(String)
    dob = Column(String)
    phone = Column(String)
    email = Column(String, index=True)


    # Insurance
    insurance_id = Column(String)
    payer = Column(String)
    copay = Column(String)

    # Visit
    department = Column(String)
    reason_for_visit = Column(String)

    # Appointment
    appointment_doctor = Column(String)
    appointment_date = Column(String)
    appointment_time = Column(String)
    appointment_status = Column(String, default="confirmed")

    # Payment
    payment_status    = Column(String, default="unpaid")
    payment_intent_id = Column(String, nullable=True)
    payment_date      = Column(String, nullable=True)
    # Meta
    created_at = Column(DateTime, default=datetime.utcnow)
    extra_data = Column(JSON, default={})
    


class IntakeSession(Base):
    __tablename__ = "intake_sessions"

    session_id = Column(String, primary_key=True, index=True)
    patient_id = Column(String, index=True)
    conversation_history = Column(JSON, default=[])
    status = Column(String, default="active")
    collected_data = Column(JSON, default={})
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


def init_db():
    Base.metadata.create_all(bind=engine)