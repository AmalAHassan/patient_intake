import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Core
    anthropic_api_key: str
    database_url: str
    redis_url: str
    fhir_base_url: str = "http://localhost:8080/fhir"

    # EHR backend — hapi_fhir | epic | athena | cerner
    ehr_backend: str = "hapi_fhir"

    # Eligibility — true = mock, false = real Availity
    use_mock_eligibility: bool = True

    # Availity (old field names kept for backwards compatibility)
    availity_api_key: str = ""
    availity_api_secret: str = ""
    # New field names used by MCP eligibility server
    availity_client_id: str = ""
    availity_client_secret: str = ""

    # Epic
    epic_client_id: str = ""
    epic_private_key: str = ""

    # Athena
    athena_client_id: str = ""
    athena_client_secret: str = ""

    # Cerner
    cerner_client_id: str = ""
    cerner_client_secret: str = ""

    # MCP server URLs (ngrok or deployed public URLs)
    mcp_patient_lookup_url: str = "http://localhost:5001/sse"
    mcp_eligibility_url: str = "http://localhost:5002/sse"
    mcp_ehr_url: str = "http://localhost:5003/sse"

    class Config:
        env_file = "../.env"
        case_sensitive = False


settings = Settings()