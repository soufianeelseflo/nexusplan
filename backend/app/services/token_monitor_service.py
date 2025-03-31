# backend/app/services/token_monitor_service.py
import telegram # Ensure 'python-telegram-bot' is in requirements.txt
import asyncio
import logging
from app.core.config import settings
from typing import Optional

logger = logging.getLogger(__name__)

# --- Token Cost Estimation (Refine based on OpenRouter's current pricing) ---
# Prices are typically per Million tokens (Input + Output)
# Example: https://openrouter.ai/models - CHECK THIS REGULARLY
MODEL_COSTS_PER_MILLION_TOKENS_USD = {
    # --- Example Prices (VERIFY AND UPDATE FROM OPENROUTER) ---
    "anthropic/claude-3-haiku-20240307": {"input": 0.25, "output": 1.25},
    "google/gemini-pro": {"input": 0.125, "output": 0.375}, # Often very cheap
    "google/gemini-1.5-flash-latest": {"input": 0.35, "output": 1.05}, # Check pricing
    "openai/gpt-4-turbo": {"input": 10.00, "output": 30.00}, # Expensive
    "openai/gpt-3.5-turbo": {"input": 0.50, "output": 1.50}, # Cheaper alternative
    "anthropic/claude-3-opus-20240229": {"input": 15.00, "output": 75.00}, # Very Expensive
    "mistralai/mistral-7b-instruct": {"input": 0.07, "output": 0.07}, # Extremely cheap
    "nousresearch/nous-hermes-2-mixtral-8x7b-dpo": {"input": 0.6, "output": 0.6}, # Good value Mixtral
    # Add vision models if used - pricing might differ
    "google/gemini-pro-vision": {"input": 0.125, "output": 0.375}, # Often same as text
    # --- Default/Fallback ---
    "default": {"input": 1.00, "output": 3.00} # Fallback estimate
}

# --- Global State (In-memory - Reset on App Restart) ---
# For persistence, use a simple file or database if needed
_current_estimated_cost_usd: float = 0.0
_token_budget_remaining_usd: float = settings.INITIAL_TOKEN_BUDGET
_low_budget_alert_sent: bool = False

# --- Telegram Bot Initialization ---
telegram_bot: Optional[telegram.Bot] = None
if settings.TELEGRAM_BOT_TOKEN:
    try:
        telegram_bot = telegram.Bot(token=settings.TELEGRAM_BOT_TOKEN)
        logger.info("Telegram Bot client initialized.")
    except Exception as e:
        logger.error(f"Failed to initialize Telegram Bot client: {e}", exc_info=True)
else:
    logger.warning("Telegram Bot Token not configured. Alerts will be disabled.")


async def send_telegram_alert(message: str):
    """Sends an alert message to the configured Telegram chat ID."""
    if telegram_bot and settings.TELEGRAM_CHAT_ID:
        try:
            # Run blocking IO in executor to avoid blocking async loop
            await asyncio.to_thread(
                telegram_bot.send_message,
                chat_id=settings.TELEGRAM_CHAT_ID,
                text=f"🚨 PHOENIX FIRE ALERT:\n{message}"
            )
            logger.info(f"Telegram alert sent: {message}")
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}", exc_info=True)
    else:
        logger.warning(f"Telegram alert skipped (not configured). Message: {message}")


def _calculate_cost(model_identifier: str, input_tokens: int, output_tokens: int) -> float:
    """Calculates the estimated cost for a given model and token count."""
    # Find the cost info, falling back to default if model not listed
    cost_info = MODEL_COSTS_PER_MILLION_TOKENS_USD.get(
        model_identifier,
        MODEL_COSTS_PER_MILLION_TOKENS_USD["default"]
    )
    if model_identifier not in MODEL_COSTS_PER_MILLION_TOKENS_USD:
        logger.warning(f"Cost info not found for model '{model_identifier}'. Using default estimate.")

    input_cost = (input_tokens / 1_000_000) * cost_info.get("input", 1.00)
    output_cost = (output_tokens / 1_000_000) * cost_info.get("output", 3.00)
    return input_cost + output_cost


async def track_token_usage(model_identifier: str, input_tokens: int, output_tokens: int):
    """
    Tracks estimated API cost, updates remaining budget, and sends alerts if needed.
    This function should be called by services making API calls (e.g., openrouter_service).
    Uses global state variables for simplicity (consider a class or DB for more complex state).
    """
    global _current_estimated_cost_usd, _token_budget_remaining_usd, _low_budget_alert_sent

    # Ensure tokens are non-negative integers
    input_tokens = max(0, int(input_tokens))
    output_tokens = max(0, int(output_tokens))

    cost = _calculate_cost(model_identifier, input_tokens, output_tokens)

    # Update global state (Consider thread safety if using threads heavily, though FastAPI runs in async loop)
    _current_estimated_cost_usd += cost
    _token_budget_remaining_usd -= cost

    logger.info(
        f"API Call Cost Tracked | Model: {model_identifier} | In: {input_tokens} | Out: {output_tokens} | "
        f"Est. Cost: ${cost:.6f} | Total Cost: ${_current_estimated_cost_usd:.4f} | Budget Left: ${_token_budget_remaining_usd:.4f}"
    )

    # Check budget threshold and send alert if needed (only once)
    if _token_budget_remaining_usd <= settings.TOKEN_BUDGET_WARN_THRESHOLD and not _low_budget_alert_sent:
        alert_message = f"Token budget low! Remaining: ~${_token_budget_remaining_usd:.2f}. Please add funds soon."
        await send_telegram_alert(alert_message)
        _low_budget_alert_sent = True # Set flag to prevent repeated alerts
    elif _token_budget_remaining_usd > settings.TOKEN_BUDGET_WARN_THRESHOLD:
        _low_budget_alert_sent = False # Reset flag if budget goes above threshold

    # Check for critically low/negative budget
    if _token_budget_remaining_usd <= 0:
         await send_telegram_alert(f"CRITICAL: Token budget exhausted or negative! Remaining: ~${_token_budget_remaining_usd:.2f}. Operations needing tokens may fail.")


def get_remaining_budget() -> float:
    """Returns the current estimated remaining budget."""
    global _token_budget_remaining_usd
    return _token_budget_remaining_usd

def get_total_estimated_cost() -> float:
    """Returns the total estimated cost incurred so far."""
    global _current_estimated_cost_usd
    return _current_estimated_cost_usd

def reset_cost_tracking(new_budget: Optional[float] = None):
    """Resets the cost tracking state, optionally setting a new budget."""
    global _current_estimated_cost_usd, _token_budget_remaining_usd, _low_budget_alert_sent
    _current_estimated_cost_usd = 0.0
    _token_budget_remaining_usd = new_budget if new_budget is not None else settings.INITIAL_TOKEN_BUDGET
    _low_budget_alert_sent = False
    logger.info(f"Token cost tracking reset. New budget: ${_token_budget_remaining_usd:.2f}")
    asyncio.create_task(send_telegram_alert(f"Token tracking reset. Current budget: ~${_token_budget_remaining_usd:.2f}"))

# --- Potentially add an API endpoint (e.g., in an admin router) ---
# --- to allow resetting the budget remotely ---
# async def update_budget(new_budget_amount: float):
#     reset_cost_tracking(new_budget_amount)
#     return {"message": f"Budget updated to ${new_budget_amount:.2f}"}