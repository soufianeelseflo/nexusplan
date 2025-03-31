# backend/app/services/branding_service.py
from app.core.config import settings
from app.services.openrouter_service import generate_with_openrouter
from app.services.cache_service import async_memory_cache
# Import library for X.com API interaction (e.g., tweepy - add to requirements.txt)
# import tweepy
import asyncio
import logging
import random

logger = logging.getLogger(__name__)

# --- X.com API Client Setup (Placeholder) ---
# Requires getting API keys for X.com (may need developer account approval)
# and configuring the client library (e.g., tweepy v2 using OAuth 2.0 Bearer Token or OAuth 1.0a)
# Store X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET in environment variables
# x_api = None
# try:
#     auth = tweepy.OAuth1UserHandler(
#         settings.X_API_KEY, settings.X_API_SECRET,
#         settings.X_ACCESS_TOKEN, settings.X_ACCESS_SECRET
#     )
#     x_api = tweepy.API(auth, wait_on_rate_limit=True)
#     x_client_v2 = tweepy.Client(
#         consumer_key=settings.X_API_KEY, consumer_secret=settings.X_API_SECRET,
#         access_token=settings.X_ACCESS_TOKEN, access_token_secret=settings.X_ACCESS_SECRET
#     )
#     logger.info("X.com API client initialized.")
# except Exception as e:
#     logger.error(f"Failed to initialize X.com API client: {e}. Branding bot posts will be disabled.")


@async_memory_cache(ttl=settings.CACHE_TTL_SECONDS // 2) # Cache for 30 mins
async def generate_branding_content_idea() -> Optional[Dict[str, Any]]:
    """Generates an idea for a branding post using AI."""
    logger.info("Generating branding content idea...")
    # Focus on topics relevant to B2B intelligence, AI, market trends, decision making
    prompt = f"""
    Act as a B2B Content Strategist for an AI-powered intelligence firm ({settings.PROJECT_NAME}).
    Generate ONE compelling content idea for an X.com post targeting executives in {', '.join(settings.TARGET_INDUSTRIES)} within {', '.join(settings.TARGET_COUNTRIES)}.
    The idea should be relevant to current business trends (Q1 2025), AI's role in strategy, or rapid decision-making.
    Suggest a format (e.g., short insight, question, mini-thread starter, link to a relevant (hypothetical) blog post).
    Include 2-3 relevant, high-volume hashtags.

    Format the output STRICTLY as a JSON object with keys: "idea_summary", "format", "hashtags" (list of strings).
    Example: {{"idea_summary": "The biggest risk in Q2 isn't the economy, it's decision latency. AI can fix that.", "format": "Short Insight", "hashtags": ["#AIStrategy", "#DecisionMaking", "#BizIntel"]}}
    """
    try:
        idea_str = await generate_with_openrouter(
            prompt=prompt,
            model_preference="balanced",
            max_tokens=150
        )
        idea_data = json.loads(idea_str)
        if isinstance(idea_data, dict) and "idea_summary" in idea_data and "format" in idea_data and "hashtags" in idea_data:
            logger.info(f"Generated branding idea: {idea_data['idea_summary']}")
            return idea_data
        else:
            logger.warning(f"AI branding idea generation returned invalid format: {idea_str}")
            return None
    except Exception as e:
        logger.error(f"Error generating branding content idea: {e}", exc_info=True)
        return None


async def craft_branding_post(idea_data: Dict[str, Any]) -> Optional[str]:
    """Crafts the actual X.com post text based on the idea."""
    logger.info(f"Crafting post for idea: {idea_data['idea_summary']}")
    prompt = f"""
    Based on the following content idea:
    Summary: {idea_data['idea_summary']}
    Format: {idea_data['format']}

    Write the actual text for an engaging X.com post (max 270 characters).
    Incorporate the suggested hashtags: {', '.join(idea_data['hashtags'])}
    If the format is 'Thread Starter', write only the first tweet of the thread, ending with a hook like '(1/n)'.
    Maintain a professional and insightful tone. Include a subtle call-to-action or link to our website [YOUR_WEBSITE_URL] if appropriate for the format, but prioritize engagement.

    Output ONLY the final post text.
    """
    try:
        post_text = await generate_with_openrouter(
            prompt=prompt,
            model_preference="flash", # Fast model for short text
            max_tokens=100 # X.com limit is 280 chars, keep AI output shorter
        )
        # Basic length check
        if len(post_text) > 280:
            post_text = post_text[:275] + "..." # Truncate crudely if needed
        logger.info(f"Crafted post text: {post_text}")
        return post_text
    except Exception as e:
        logger.error(f"Error crafting branding post text: {e}", exc_info=True)
        return None


async def post_to_x_com(post_text: str):
    """Posts the generated text to the configured X.com account."""
    # if not x_client_v2: # Check if client initialized
    #     logger.warning("X.com client not available. Skipping post.")
    #     return False

    logger.warning("X.com posting functionality is a placeholder. Requires valid X API v2 client setup.")
    print(f"--- SIMULATED X.COM POST ---")
    print(post_text)
    print(f"---------------------------")
    await asyncio.sleep(1) # Simulate API call delay
    return True # Return True for simulation

    # try:
    #     response = x_client_v2.create_tweet(text=post_text)
    #     logger.info(f"Successfully posted to X.com. Tweet ID: {response.data['id']}")
    #     return True
    # except Exception as e:
    #     logger.error(f"Failed to post to X.com: {e}", exc_info=True)
    #     # Consider sending Telegram alert on repeated failures
    #     return False


async def run_branding_cycle():
    """Generates and posts branding content."""
    logger.info("--- Running Branding Cycle ---")
    try:
        # 1. Generate Idea
        idea = await generate_branding_content_idea()
        if not idea:
            logger.warning("Could not generate branding idea.")
            return

        # 2. Craft Post
        post_text = await craft_branding_post(idea)
        if not post_text:
            logger.warning("Could not craft branding post text.")
            return

        # 3. Post to X.com (Simulated)
        await post_to_x_com(post_text)

    except Exception as e:
        logger.error(f"Error during branding cycle: {e}", exc_info=True)

    logger.info("--- Branding Cycle Finished ---")