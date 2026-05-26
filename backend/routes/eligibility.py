from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from services import eligibility

router = APIRouter()


class EligibilityRequest(BaseModel):
    insurance_id: str
    payer: str


@router.post("/check")
async def check_eligibility(request: EligibilityRequest):
    """Check insurance eligibility."""
    try:
        result = eligibility.check_eligibility(request.insurance_id, request.payer)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
