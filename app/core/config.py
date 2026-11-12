from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_NAME: str = "AI SURVIVOR — Full Autonomous Production Engine"
    ENVIRONMENT: str = "production"
    DATABASE_URL: str = "sqlite:///./ai_survivor_p1.db"
    ADMIN_TOKEN: str = "change-me-to-a-strong-secret-token-98765"

    INITIAL_CAPITAL: float = 5000.0
    EMERGENCY_RESERVE_RATIO: float = 0.20
    MAX_SINGLE_ALLOCATION_RATIO: float = 0.30
    PAPER_MODE_ONLY: bool = True

    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_MODEL: str = "gpt-4o-mini"

    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    AUTO_CYCLE_INTERVAL_SECONDS: int = 60

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
