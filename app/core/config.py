from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_NAME: str = "AI SURVIVOR — Phase 1 Core Engine"
    ENVIRONMENT: str = "development"
    DATABASE_URL: str = "sqlite:///./ai_survivor_p1.db"
    ADMIN_TOKEN: str = "change-me-to-a-strong-secret-token-98765"

    INITIAL_CAPITAL: float = 5000.0
    EMERGENCY_RESERVE_RATIO: float = 0.20
    MAX_SINGLE_ALLOCATION_RATIO: float = 0.30
    PAPER_MODE_ONLY: bool = True

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
