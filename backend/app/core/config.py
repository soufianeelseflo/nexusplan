# backend/app/core/config.py
import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings
from typing import List, Optional, Dict
import logging

# Configure logging early
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
logger = logging.getLogger(__name__)

# Determine base directory more reliably
# Assumes .env is in the 'backend' directory, parent of 'app' directory
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOTENV_PATH = os.path.join(BASE_DIR, '.env')

# Load .env file variables into environment if it exists
if os.path.exists(DOTENV_PATH):
    load_dotenv(dotenv_path=DOTENV_PATH)
    logger.info(f".env file loaded from: {DOTENV_PATH}")
else:
    logger.warning(f".env file not found at {DOTENV_PATH}. Relying on system environment variables.")


class Settings(BaseSettings):
    PROJECT_NAME: str = "Operation Phoenix Fire MAX ARCANA"
    API_V1_STR: str = "/api/v1"
    ENCODING: str = "UTF-8"

    # --- Critical Secrets ---
    OPENROUTER_API_KEY: str
    GEMINI_API_KEY: Optional[str] = None

    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_CHAT_ID: str

    TWILIO_ACCOUNT_SID: str
    TWILIO_AUTH_TOKEN: str
    TWILIO_PHONE_NUMBER: str # E.164 format, e.g., +14155552671

    DEEPGRAM_API_KEY: str
    ELEVENLABS_API_KEY: str
    ELEVENLABS_VOICE_ID: str = "21m00Tcm4TlvDq8ikWAM" # Default Rachel voice ID

    LEMONSQUEEZY_WEBHOOK_SECRET: str
    LEMONSQUEEZY_API_KEY: Optional[str] = None

    SMARTPROXY_USER: str
    SMARTPROXY_PASS: str
    SMARTPROXY_HOST: str
    SMARTPROXY_PORT: str

    DOMAIN_EMAIL_USER: str
    DOMAIN_EMAIL_PASSWORD: str
    DOMAIN_EMAIL_SMTP_SERVER: str
    DOMAIN_EMAIL_SMTP_PORT: int = 587

    # --- Operational Settings ---
    TARGET_COUNTRIES: List[str] = ["US", "UK", "DE", "CA", "AU"]
    TARGET_INDUSTRIES: List[str] = ["Technology", "Finance", "Healthcare", "Industrials"]
    REPORT_PRICE_STANDARD: int = 750
    REPORT_PRICE_PREMIUM: int = 1200
    TOKEN_BUDGET_WARN_THRESHOLD: float = 10.0
    MAX_CONCURRENT_TASKS: int = 3
    INITIAL_TOKEN_BUDGET: float = 50.0
    CACHE_TTL_SECONDS: int = 3600
    SCHEDULER_INTERVAL_MINUTES: int = 60 # How often the main cycle checks for work

    # --- Computed Proxy Settings ---
    @property
    def proxy_url(self) -> Optional[str]:
        if self.SMARTPROXY_USER and self.SMARTPROXY_PASS and self.SMARTPROXY_HOST and self.SMARTPROXY_PORT:
            # Ensure proper URL encoding if username/password contain special characters
            # from urllib.parse import quote_plus
            # user = quote_plus(self.SMARTPROXY_USER)
            # pwd = quote_plus(self.SMARTPROXY_PASS)
            # return f"http://{user}:{pwd}@{self.SMARTPROXY_HOST}:{self.SMARTPROXY_PORT}"
            # Assuming simple user/pass for now:
            return f"http://{self.SMARTPROXY_USER}:{self.SMARTPROXY_PASS}@{self.SMARTPROXY_HOST}:{self.SMARTPROXY_PORT}"
        return None

    @property
    def proxies(self) -> Optional[Dict[str, str]]:
        url = self.proxy_url
        return {"http://": url, "https://": url} if url else None

    class Config:
        # Tells pydantic-settings where to look for env vars
        # Order matters if multiple sources are used
        env_file = DOTENV_PATH if os.path.exists(DOTENV_PATH) else None
        env_file_encoding = 'utf-8'
        # Allow reading variables even if .env is not found (from system env)
        extra = 'ignore'

# Instantiate settings globally
try:
    settings = Settings()
    logger.info("Settings loaded successfully.")
    logger.info(f"Project Name: {settings.PROJECT_NAME}")
    logger.info(f"Proxy Configured: {'Yes' if settings.proxy_url else 'No'}")
    # Avoid logging sensitive keys even during startup
except Exception as e:
    logger.critical(f"CRITICAL ERROR: Failed to load settings. Check environment variables and .env file ({DOTENV_PATH}). Error: {e}", exc_info=True)
    # Application cannot run without settings
    raise SystemExit(f"CRITICAL ERROR: Settings loading failed. Exiting. Error: {e}")