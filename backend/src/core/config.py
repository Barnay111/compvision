from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "CompVision Restaurant AI API"
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5435/compvision"
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 8002

    # Telegram reports: create a bot with @BotFather and put its token here (or in backend/.env).
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_API_BASE: str = "https://api.telegram.org"
    REPORTS_ENABLED: bool = True          # background sender of daily reports
    DASHBOARD_URL: str = ""               # optional link added to the bottom of reports

    class Config:
        env_file = ".env"

settings = Settings()
