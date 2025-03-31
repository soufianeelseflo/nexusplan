# backend/app/services/openrouter_service.py
import httpx # Use httpx for robust async requests and proxy support
import asyncio
import logging
from app.core.config import settings, PROXIES # Import settings and pre-configured proxies dict
from app.services.cache_service import async_ttl_cache # Import caching decorator
from app.services.token_monitor_service import track_token_usage # Import token tracking
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# --- OpenRouter API Endpoint ---
OPENROUTER_API_BASE_URL = "https://openrouter.ai/api/v1"

# --- Model Preferences Mapping ---
# Map simple preference keys to actual OpenRouter model identifiers
# Keep this updated based on OpenRouter's available models and pricing
MODEL_PREFERENCES = {
    "cheap_fast": "anthropic/claude-3-haiku-20240307",
    "balanced": "google/gemini-pro",
    "high_quality": "openai/gpt-4-turbo", # Or "anthropic/claude-3-opus-20240229"
    "vision": "google/gemini-pro-vision", # Or "openai/gpt-4-vision-preview"
    "flash": "google/gemini-1.5-flash-latest"
}
DEFAULT_MODEL = MODEL_PREFERENCES["balanced"]

# --- Core Generation Function ---
@async_ttl_cache() # Use default cache settings from cache_service
async def generate_with_openrouter(
    prompt: str,
    model_preference: str = "balanced",
    system_prompt: Optional[str] = None,
    max_tokens: int = 2000, # Default max tokens
    temperature: float = 0.7,
    retry_attempts: int = 2,
    initial_delay: float = 1.0
) -> str:
    """
    Generates text using a specified model preference via the OpenRouter API.
    Handles model selection, API call, error handling, retries, caching, and token tracking.
    """
    model_name = MODEL_PREFERENCES.get(model_preference, DEFAULT_MODEL)
    logger.info(f"Initiating generation via OpenRouter. Model preference: '{model_preference}' -> Actual model: '{model_name}'")

    if not settings.OPENROUTER_API_KEY:
        logger.critical("OpenRouter API Key is not configured. Cannot generate text.")
        raise ValueError("OpenRouter API Key not configured.")

    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        # Recommended headers by OpenRouter:
        "HTTP-Referer": f"https://{settings.PROJECT_NAME.lower().replace(' ', '')}.com", # Replace with your actual site URL later
        "X-Title": settings.PROJECT_NAME,
    }

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model_name,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        # Add other parameters like top_p, presence_penalty etc. if needed
        # "stream": False, # Not using streaming for this function
    }

    current_attempt = 0
    last_exception = None
    while current_attempt <= retry_attempts:
        current_attempt += 1
        logger.debug(f"OpenRouter API Call - Attempt {current_attempt}/{retry_attempts+1}")
        try:
            async with httpx.AsyncClient(proxies=PROXIES, timeout=120.0) as client: # Increased timeout for potentially long generations
                response = await client.post(
                    f"{OPENROUTER_API_BASE_URL}/chat/completions",
                    headers=headers,
                    json=payload
                )

                # Check for common non-200 status codes
                if response.status_code == 401:
                    logger.critical("OpenRouter Authentication Error (401). Check API Key.")
                    await token_monitor_service.send_telegram_alert("CRITICAL: OpenRouter API Key Invalid (401)!")
                    raise HTTPException(status_code=401, detail="OpenRouter authentication failed.")
                if response.status_code == 402:
                    logger.critical("OpenRouter Payment Required (402). Account out of credits?")
                    await token_monitor_service.send_telegram_alert("CRITICAL: OpenRouter Payment Required (402)! Check account balance.")
                    raise HTTPException(status_code=402, detail="OpenRouter payment required.")
                if response.status_code == 429:
                    logger.warning(f"OpenRouter Rate Limit Exceeded (429) on attempt {current_attempt}.")
                    last_exception = HTTPException(status_code=429, detail="OpenRouter rate limit exceeded.")
                    # Implement exponential backoff for rate limits
                    delay = initial_delay * (2 ** current_attempt) + random.uniform(0, 2)
                    logger.info(f"Rate limit hit. Waiting {delay:.2f} seconds before retry...")
                    await asyncio.sleep(delay)
                    continue # Go to next retry attempt

                # Raise exceptions for other client/server errors (4xx, 5xx)
                response.raise_for_status()

                # --- Process Successful Response ---
                result_data = response.json()
                logger.debug(f"OpenRouter Raw Response: {result_data}")

                if result_data and result_data.get("choices") and result_data["choices"][0].get("message"):
                    content = result_data["choices"][0]["message"].get("content", "")
                    usage = result_data.get("usage", {})
                    input_tokens = usage.get("prompt_tokens", 0)
                    output_tokens = usage.get("completion_tokens", 0)

                    # Crude estimation if API doesn't provide tokens (less likely with OpenRouter)
                    if input_tokens == 0: input_tokens = len(prompt.split()) // 0.7
                    if output_tokens == 0: output_tokens = len(content.split()) // 0.7

                    # Track token usage asynchronously
                    asyncio.create_task(track_token_usage(model_name, int(input_tokens), int(output_tokens)))

                    logger.info(f"OpenRouter generation successful. Model: {model_name}, Tokens: In={input_tokens}, Out={output_tokens}")
                    return content.strip() # Return the generated content
                else:
                    logger.error(f"OpenRouter response format unexpected: {result_data}")
                    last_exception = ValueError("Invalid response format from OpenRouter.")
                    # Don't retry format errors usually
                    break # Exit retry loop

        except httpx.TimeoutException as e:
            logger.warning(f"OpenRouter request timed out on attempt {current_attempt}: {e}")
            last_exception = e
            # Retry on timeouts
            if current_attempt <= retry_attempts:
                delay = initial_delay * (2 ** (current_attempt - 1)) + random.uniform(0, 1)
                await asyncio.sleep(delay)
            else:
                logger.error(f"OpenRouter request failed after {retry_attempts + 1} attempts due to timeout.")
                break # Exit retry loop
        except httpx.RequestError as e:
            logger.error(f"Network error calling OpenRouter on attempt {current_attempt}: {e}", exc_info=True)
            last_exception = e
            # Retry network errors
            if current_attempt <= retry_attempts:
                delay = initial_delay * (2 ** (current_attempt - 1)) + random.uniform(0, 1)
                await asyncio.sleep(delay)
            else:
                logger.error(f"OpenRouter request failed after {retry_attempts + 1} attempts due to network error.")
                break # Exit retry loop
        except HTTPException as e:
             # Handle specific HTTP exceptions raised above (like 401, 402) - don't retry these
             logger.error(f"HTTP error during OpenRouter call: {e.detail} (Status: {e.status_code})")
             last_exception = e
             break # Exit retry loop
        except Exception as e:
            logger.critical(f"Unexpected error during OpenRouter call on attempt {current_attempt}: {e}", exc_info=True)
            last_exception = e
            # Don't retry unknown errors immediately
            break # Exit retry loop

    # If loop finishes without returning success
    error_message = f"Failed to generate text via OpenRouter after {retry_attempts + 1} attempts. Last error: {last_exception}"
    logger.error(error_message)
    # Send critical alert if it fails consistently
    await token_monitor_service.send_telegram_alert(f"ERROR: OpenRouter generation failed repeatedly! Last Error: {last_exception}")
    raise ConnectionError(error_message) # Raise an exception to signal failure to the caller

# Add functions for vision models if needed, adapting the payload structure
# async def analyze_image_with_openrouter(prompt: str, image_data_base64: str):
#    model_name = MODEL_PREFERENCES["vision"]
#    payload = { ... messages: [{"role": "user", "content": [ {"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data_base64}"}} ]}] ... }
#    # ... rest of the API call logic ...
#    pass