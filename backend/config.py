import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str
    database_url: str
    redis_url: str
    fhir_base_url: str = "http://localhost:8080/fhir"
    availity_api_key: str = ""
    availity_api_secret: str = ""

    class Config:
        env_file = "../.env"
        case_sensitive = False


settings = Settings()
