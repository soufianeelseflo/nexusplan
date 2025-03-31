# backend/app/main.py
import asyncio
import threading
import time
import schedule # Ensure 'schedule' is in requirements.txt
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware # If needed for frontend later
from app.core.config import settings # Import the instantiated settings
from app.api.api_v1.api import api_router_v1 # Import the v1 router aggregator
from app.services import automation_service, token_monitor_service, branding_service # Import services with scheduled tasks

# --- Logging Configuration ---
# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)-8s - %(name)-15s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
# Optionally set lower levels for specific modules if needed for debugging
# logging.getLogger('app.services.openrouter_service').setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)

# --- Application Setup ---
if settings is None:
    logger.critical("Settings failed to load. Application cannot start.")
    raise SystemExit("CRITICAL ERROR: Settings loading failed.")

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="AI-Powered Rapid Intelligence Report Generation and Outreach System.",
    version="1.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs", # Swagger UI
    redoc_url=f"{settings.API_V1_STR}/redoc" # ReDoc
)

# --- Middleware ---
# Add CORS middleware if requests will come from a browser frontend
# origins = [
#     "YOUR_WEBSITE_DOMAIN", # e.g., "https://rapidintelsolutions.io"
#     # Add other origins if needed, like localhost for development
# ]
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"], # Allow all origins for now, restrict in production
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# --- Include API Routers ---
app.include_router(api_router_v1, prefix=settings.API_V1_STR)

# --- Root Endpoint ---
@app.get("/", tags=["Root"], summary="Application Root Endpoint")
async def read_root():
    """Provides basic status information about the application."""
    return {"message": f"Welcome to {settings.PROJECT_NAME}", "status": "Operational"}

# --- Background Task Scheduler Function ---
def _run_scheduled_tasks_sync():
    """Synchronous wrapper to run scheduled jobs in a loop. Executed in a separate thread."""
    logger.info("Background task scheduler thread started.")

    # Get or create an event loop for this thread if needed by scheduled async tasks
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    # --- Define Scheduled Jobs ---
    # Schedule the main AI cycle (find triggers, outreach)
    schedule.every(settings.SCHEDULER_INTERVAL_MINUTES).minutes.do(
        lambda: loop.run_until_complete(automation_service.run_main_cycle())
    )
    logger.info(f"Scheduled main automation cycle every {settings.SCHEDULER_INTERVAL_MINUTES} minutes.")

    # Schedule the branding bot post (example - adjust frequency)
    schedule.every(4).to(8).hours.do( # Run every 4-8 hours
        lambda: loop.run_until_complete(branding_service.run_branding_cycle())
    )
    logger.info("Scheduled branding bot cycle every 4-8 hours.")

    # --- Scheduler Loop ---
    while True:
        try:
            schedule.run_pending()
        except Exception as e:
            logger.error(f"Error during scheduled task execution: {e}", exc_info=True)
            # Consider adding alerts via token_monitor_service.send_telegram_alert
        # Sleep for a reasonable interval
        time.sleep(max(10, settings.SCHEDULER_INTERVAL_MINUTES * 60 // 10)) # Check roughly 10 times per cycle interval, but at least every 10s

# --- FastAPI Startup Event ---
@app.on_event("startup")
async def startup_event():
    """Actions to perform on application startup."""
    logger.info(f"Starting up {settings.PROJECT_NAME}...")

    # Initialize token budget from settings
    token_monitor_service.reset_cost_tracking(new_budget=settings.INITIAL_TOKEN_BUDGET)
    logger.info(f"Initial token budget set to: ${settings.INITIAL_TOKEN_BUDGET:.2f}")

    # Start the background scheduler in a separate thread
    scheduler_thread = threading.Thread(target=_run_scheduled_tasks_sync, daemon=True, name="SchedulerThread")
    scheduler_thread.start()
    logger.info("Background scheduler thread initiated.")

    # Perform any other async initializations here if needed
    # e.g., await database.connect()

    logger.info(f"{settings.PROJECT_NAME} startup complete. API available at {settings.API_V1_STR}")

# --- FastAPI Shutdown Event ---
@app.on_event("shutdown")
async def shutdown_event():
    """Actions to perform on application shutdown."""
    logger.info(f"Shutting down {settings.PROJECT_NAME}...")
    # Clear schedule to prevent new jobs from starting during shutdown
    schedule.clear()
    logger.info("Scheduled tasks cleared.")
    # Add any other cleanup tasks here
    # e.g., await database.disconnect()
    logger.info(f"{settings.PROJECT_NAME} shutdown complete.")