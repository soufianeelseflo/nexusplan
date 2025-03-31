# backend/app/services/branding_service.py
from app.core.config import settings
from app.services.openrouter_service import generate_with_openrouter
from app.services.cache_service import async_ttl_cache
# Import library for X.com API interaction (e.g., tweepy)
# Ensure 'tweepy' is in requirements.txt if uncommenting API calls
# import tweepy
import asyncio
import logging
import random
import json
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# --- X.com API Client Setup (Requires User Credentials in .env) ---
# This section attempts initialization but gracefully handles failure.
x_client_v2 = None
X_API_ENABLED = False
# Uncomment these lines in .env.example and provide keys if using X.com API
# X_API_KEY="YOUR_X_CONSUMER_KEY"
# X_API_SECRET="YOUR_X_CONSUMER_SECRET"
# X_ACCESS_TOKEN="YOUR_X_ACCESS_TOKEN"
# X_ACCESS_SECRET="YOUR_X_ACCESS_SECRET_TOKEN"

# try:
#     if all([settings.X_API_KEY, settings.X_API_SECRET, settings.X_ACCESS_TOKEN, settings.X_ACCESS_SECRET]):
#         x_client_v2 = tweepy.Client(
#             consumer_key=settings.X_API_KEY, consumer_secret=settings.X_API_SECRET,
#             access_token=settings.X_ACCESS_TOKEN, access_token_secret=settings.X_ACCESS_SECRET,
#             wait_on_rate_limit=True # Automatically handle rate limits if possible
#         )
#         # Verify credentials work
#         me = x_client_v2.get_me()
#         if me.data:
#             logger.info(f"X.com API client initialized successfully for user @{me.data.username}.")
#             X_API_ENABLED = True
#         else:
#             logger.error("X.com API client initialized but failed to verify credentials.")
#             x_client_v2 = None
#     else:
#         logger.warning("X.com API credentials not fully configured in environment variables. X.com posting will be disabled.")
# except ImportError:
#     logger.warning("Tweepy library not installed (`pip install tweepy`). X.com posting disabled.")
# except Exception as e:
#     logger.error(f"Failed to initialize X.com API client: {e}. Branding bot posts will be disabled.", exc_info=True)

# --- Content Generation ---
@async_ttl_cache(ttl=settings.CACHE_TTL_SECONDS // 4) # Cache ideas for 15 mins
async def generate_branding_content_idea() -> Optional[Dict[str, Any]]:
    """
    Generates a compelling content idea for X.com using AI (via OpenRouter).
    Applies "Think Tool": Specific prompt, JSON validation, error handling.
    """
    logger.info("Generating branding content idea...")
    prompt = f"""
    Act as a sharp B2B Content Strategist for {settings.PROJECT_NAME}, an AI-powered rapid intelligence firm.
    Generate ONE unique, engaging content idea for an X.com post targeting executives and strategists in {', '.join(settings.TARGET_INDUSTRIES)} (focus on Tech & Finance) within {', '.join(settings.TARGET_COUNTRIES)}.
    The idea must be highly relevant to current business challenges (Q1/Q2 2025), the strategic use of AI/data, or the importance of speed in decision-making. Avoid generic platitudes.
    Suggest an effective format: "Short Insight", "Provocative Question", "Mini-Thread Starter (1/3)", "Data Point + Interpretation".
    Include 3 relevant, specific, and moderately high-volume hashtags (mix broad and niche).

    Format the output STRICTLY as a valid JSON object with keys: "idea_summary" (string, max 150 chars), "format" (string), "hashtags" (list of 3 strings).
    Example: {{"idea_summary": "Competitor analysis is useless if it's 2 weeks old. Real-time AI intel is the new table stakes.", "format": "Short Insight", "hashtags": ["#CompetitiveIntelligence", "#AI", "#DecisionSpeed"]}}
    Output ONLY the JSON object.
    """
    try:
        idea_str = await generate_with_openrouter(
            prompt=prompt,
            model_preference="balanced", # Good for creative but structured output
            max_tokens=200,
            temperature=0.7
        )
        # --- Input/Output Validation ---
        try:
            # Find JSON within potential AI commentary
            json_start = idea_str.find('{')
            json_end = idea_str.rfind('}') + 1
            if json_start != -1 and json_end != -1:
                json_str = idea_str[json_start:json_end]
                idea_data = json.loads(json_str)
            else:
                raise json.JSONDecodeError("No valid JSON object found", idea_str, 0)

            if isinstance(idea_data, dict) and \
               all(k in idea_data for k in ["idea_summary", "format", "hashtags"]) and \
               isinstance(idea_data["idea_summary"], str) and \
               isinstance(idea_data["format"], str) and \
               isinstance(idea_data["hashtags"], list) and \
               len(idea_data["hashtags"]) == 3 and \
               all(isinstance(h, str) for h in idea_data["hashtags"]):
                logger.info(f"Generated valid branding idea: {idea_data['idea_summary']}")
                return idea_data
            else:
                logger.warning(f"AI branding idea generation returned invalid JSON structure: {idea_str}")
                return None
        except json.JSONDecodeError as json_err:
            logger.error(f"Failed to decode JSON response for branding idea: {idea_str}. Error: {json_err}", exc_info=False)
            return None

    except ConnectionError as conn_err:
        logger.error(f"Connection error generating branding idea: {conn_err}", exc_info=False)
        return None
    except Exception as e:
        logger.error(f"Unexpected error generating branding content idea: {e}", exc_info=True)
        return None


async def craft_branding_post(idea_data: Dict[str, Any]) -> Optional[str]:
    """
    Crafts the actual X.com post text based on the generated idea using AI.
    Applies "Think Tool": Specific prompt, length check, error handling.
    """
    logger.info(f"Crafting X.com post for idea: {idea_data['idea_summary']}")
    website_url = "YOUR_DEPLOYED_WEBSITE_URL" # Replace with actual URL

    prompt = f"""
    Based on the following content idea:
    Summary: {idea_data['idea_summary']}
    Format: {idea_data['format']}
    Hashtags: {', '.join(idea_data['hashtags'])}

    Write the final, engaging X.com post text (strict maximum 275 characters).
    - If format is 'Thread Starter', end with "(1/3) 🧵👇".
    - If format is 'Short Insight' or 'Data Point', be concise and impactful.
    - If format is 'Provocative Question', pose the question clearly.
    - Incorporate the hashtags naturally at the end.
    - Maintain a highly professional, authoritative, and forward-thinking tone suitable for {settings.PROJECT_NAME}.
    - Optionally include the website URL [{website_url}] if it fits naturally and adds value (e.g., for a thread starter).

    Output ONLY the final post text, ready for publishing.
    """
    try:
        # Use a fast model optimized for short, creative text
        post_text = await generate_with_openrouter(
            prompt=prompt,
            model_preference="flash",
            max_tokens=120, # Keep it well under X.com limit
            temperature=0.65
        )
        # --- Output Validation ---
        if not post_text or len(post_text) > 280: # Check length constraint
            logger.warning(f"Generated post text failed validation (length: {len(post_text)}). Text: '{post_text}'")
            # Attempt to truncate if slightly over, otherwise fail
            if len(post_text) > 280 and len(post_text) < 300:
                 post_text = post_text[:277] + "..."
                 logger.info(f"Truncated post text: {post_text}")
                 return post_text.strip()
            else:
                 return None # Fail if significantly over or empty

        logger.info(f"Successfully crafted post text: {post_text}")
        return post_text.strip()
    except ConnectionError as conn_err:
        logger.error(f"Connection error crafting branding post: {conn_err}", exc_info=False)
        return None
    except Exception as e:
        logger.error(f"Unexpected error crafting branding post text: {e}", exc_info=True)
        return None


async def post_to_x_com(post_text: str) -> bool:
    """
    Posts the generated text to the configured X.com account using Tweepy Client v2.
    Includes basic error handling.
    """
    global X_API_ENABLED, x_client_v2
    if not X_API_ENABLED or not x_client_v2:
        logger.warning("X.com client not available or not enabled. Skipping post.")
        print(f"--- SIMULATED X.COM POST (API Disabled) ---")
        print(post_text)
        print(f"-----------------------------------------")
        await asyncio.sleep(0.1) # Minimal delay for simulation
        return False # Indicate posting was skipped/simulated

    logger.info(f"Attempting to post to X.com: '{post_text[:50]}...'")
    try:
        # Use Tweepy v2 client
        # Run blocking API call in executor thread
        response = await asyncio.to_thread(x_client_v2.create_tweet, text=post_text)
        tweet_id = response.data['id']
        logger.info(f"Successfully posted to X.com. Tweet ID: {tweet_id}")
        return True
    except Exception as e: # Catch potential TweepyHTTPException or others
        logger.error(f"Failed to post to X.com: {e}", exc_info=True)
        # Consider specific error handling for rate limits, duplicate content, etc.
        # Example: if isinstance(e, tweepy.errors.Forbidden) and 'duplicate content' in str(e): logger.warning("Duplicate tweet detected.")
        await send_telegram_alert(f"ERROR: Failed to post branding content to X.com! Error: {e}")
        return False


async def run_branding_cycle():
    """
    Autonomous cycle for generating and posting branding content to X.com.
    Triggered by the scheduler. Includes "Think Tool" checks.
    """
    logger.info("--- Running Branding Cycle ---")
    try:
        # --- Pre-computation Check: API Enabled ---
        if not X_API_ENABLED:
            logger.info("Branding cycle skipped: X.com API not enabled.")
            return

        # 1. Generate Content Idea ("Think": Validates output)
        idea = await generate_branding_content_idea()
        if not idea:
            logger.warning("Branding cycle failed: Could not generate valid content idea.")
            return

        # 2. Craft Post Text ("Think": Validates output)
        post_text = await craft_branding_post(idea)
        if not post_text:
            logger.warning("Branding cycle failed: Could not craft valid post text.")
            return

        # 3. Post to X.com ("Think": Handles API errors)
        await post_to_x_com(post_text)
        # Success/failure logged within post_to_x_com

    except Exception as e:
        logger.error(f"Unexpected error during branding cycle: {e}", exc_info=True)
        # Send alert for unexpected cycle failure
        await send_telegram_alert(f"ERROR: Unexpected failure in branding cycle: {e}")

    logger.info("--- Branding Cycle Finished ---")