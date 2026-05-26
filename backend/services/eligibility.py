from config import settings


def check_eligibility(insurance_id: str, payer: str) -> dict:
    """Check insurance eligibility."""
    if settings.availity_api_key:
        return _check_availity(insurance_id, payer)

    return {
        "covered": True,
        "plan": "Blue Cross PPO",
        "copay": "$25",
        "deductible_met": False,
        "deductible_remaining": "$500",
    }


def _check_availity(insurance_id: str, payer: str) -> dict:
    """Check eligibility via Availity API (placeholder)."""
    return {
        "covered": True,
        "plan": "Blue Cross PPO",
        "copay": "$25",
        "deductible_met": False,
        "deductible_remaining": "$500",
    }
