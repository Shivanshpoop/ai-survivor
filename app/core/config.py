from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_NAME: str = "NovaCraft Studio — Digital Tools, Services & Merch"
    ENVIRONMENT: str = "production"
    DATABASE_URL: str = "sqlite:///./ai_survivor_p1.db"
    ADMIN_TOKEN: str = "change-me-to-a-strong-secret-token-98765"
    HIDDEN_ADMIN_PATH: str = "/ops-control-98765"

    INITIAL_CAPITAL: float = 5000.0
    EMERGENCY_RESERVE_RATIO: float = 0.20
    MAX_SINGLE_ALLOCATION_RATIO: float = 0.30
    PAPER_MODE_ONLY: bool = False

    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    LLM_MODEL: str = "gemini-2.5-flash"

    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    AUTO_CYCLE_INTERVAL_SECONDS: int = 30

    FAMPAY_UPI_ID: str = "demo@upi"
    FAMPAY_PAYEE_NAME: str = "NovaCraft Studio"
    BUSINESS_EMAIL: str = "contact@example.com"
    PUBLIC_STORE_URL: str = "https://ai-survivor.onrender.com"

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
