# backend/app/services/scraping_service.py
import httpx
from bs4 import BeautifulSoup
import asyncio
import logging
from app.core.config import settings, PROXIES # Import settings and proxy dict
from app.services.cache_service import async_ttl_cache
from typing import Optional, List, Dict, Any

# --- Selenium/Playwright Imports (Conditional) ---
# Only import if dynamic scraping is truly needed and setup is complete
# from selenium import webdriver
# from selenium.webdriver.chrome.service import Service as ChromeService
# from selenium.webdriver.chrome.options import Options as ChromeOptions
# from webdriver_manager.chrome import ChromeDriverManager
# from selenium.common.exceptions import WebDriverException
# import playwright.async_api

logger = logging.getLogger(__name__)

# --- Default Headers ---
DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36', # Keep user agent reasonably updated
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Sec-Ch-Ua': '"Google Chrome";v="123", "Not:A-Brand";v="8", "Chromium";v="123"',
    'Sec-Ch-Ua-Mobile': '?0',
    'Sec-Ch-Ua-Platform': '"Windows"' # Or appropriate platform
}

# --- Static Content Scraping (Using httpx) ---
@async_ttl_cache(ttl=settings.CACHE_TTL_SECONDS // 2) # Cache scrapes for 30 mins
async def scrape_url_content_static(url: str, timeout: float = 20.0) -> Optional[str]:
    """
    Scrapes static HTML content from a URL using httpx and BeautifulSoup.
    Returns the main text content found.
    """
    logger.info(f"Attempting static scrape: {url}")
    try:
        async with httpx.AsyncClient(
            proxies=settings.proxies, # Use configured proxies
            headers=DEFAULT_HEADERS,
            follow_redirects=True,
            timeout=timeout,
            verify=False # Added to ignore SSL errors, use with caution
        ) as client:
            response = await client.get(url)
            response.raise_for_status() # Raise HTTPStatusError for bad responses (4xx or 5xx)

            # Check content type - only parse HTML
            content_type = response.headers.get('content-type', '').lower()
            if 'html' not in content_type:
                logger.warning(f"Skipping non-HTML content type ('{content_type}') for URL: {url}")
                return None

            # Parse HTML content
            soup = BeautifulSoup(response.text, 'lxml') # Use lxml for speed

            # --- Improved Text Extraction Logic ---
            # Remove script, style, header, footer, nav tags
            for element in soup(["script", "style", "header", "footer", "nav", "aside", "form", "button", "iframe"]):
                element.decompose()

            # Get text from main content areas if possible (common tags/ids)
            main_content = soup.find('main') or soup.find('article') or soup.find('div', id='content') or soup.find('div', class_='content') or soup.body
            if main_content:
                text = main_content.get_text(separator='\n', strip=True)
            else: # Fallback to whole body if no main content found
                text = soup.get_text(separator='\n', strip=True)

            # Basic cleaning - remove excessive blank lines
            cleaned_text = "\n".join(line for line in text.splitlines() if line.strip())

            logger.info(f"Static scrape successful for {url}. Content length: {len(cleaned_text)}")
            # Limit content length returned to avoid overwhelming AI context windows
            return cleaned_text[:20000] # Limit to ~20k chars

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error during static scrape of {url}: Status {e.response.status_code}", exc_info=False) # Log less detail for common HTTP errors
        return None
    except httpx.RequestError as e:
        logger.error(f"Network error during static scrape of {url}: {e}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"Unexpected error during static scrape of {url}: {e}", exc_info=True)
        return None


# --- Dynamic Content Scraping (Framework/Placeholder) ---
# Requires Selenium/Playwright setup in the Dockerfile and environment.
# This section provides the structure but not the full implementation due to complexity.
async def scrape_url_content_dynamic(url: str, timeout: float = 45.0) -> Optional[str]:
    """
    Placeholder/Framework for scraping dynamic content requiring JavaScript execution.
    Uses Selenium/Playwright (requires setup). Falls back to static scrape on failure.
    """
    logger.info(f"Attempting dynamic scrape (requires browser automation setup): {url}")

    # --- Check if Browser Automation Tools are Available ---
    # Add a check here (e.g., try importing playwright/selenium) or use a config flag
    BROWSER_AUTOMATION_ENABLED = False # Set to True if Selenium/Playwright is configured

    if not BROWSER_AUTOMATION_ENABLED:
        logger.warning("Browser automation not enabled/configured. Falling back to static scrape.")
        return await scrape_url_content_static(url, timeout=timeout)

    # --- Playwright Implementation Example (Conceptual) ---
    # try:
    #     async with playwright.async_api.async_playwright() as p:
    #         # Configure browser launch options (headless, proxy, user agent, etc.)
    #         browser_options = {
    #             "headless": True,
    #             "proxy": {"server": settings.proxy_url} if settings.proxy_url else None,
    #             # Add more options for stealth: user_agent, viewport, etc.
    #         }
    #         browser = await p.chromium.launch(**browser_options)
    #         page = await browser.new_page()
    #         await page.goto(url, timeout=int(timeout * 1000), wait_until='networkidle') # Wait for network to be idle

    #         # --- Add Logic to Handle Dynamic Elements ---
    #         # Examples: Wait for specific selectors, click buttons, scroll down
    #         # await page.wait_for_selector("#dynamic-content-id", timeout=10000)
    #         # await page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
    #         # await asyncio.sleep(3) # Wait for content loaded after scroll

    #         # Extract content after JS execution
    #         html_content = await page.content()
    #         await browser.close()

    #         # Parse the dynamically rendered HTML
    #         soup = BeautifulSoup(html_content, 'lxml')
    #         # Use similar text extraction logic as static scrape
    #         for element in soup(["script", "style", "header", "footer", "nav", "aside", "form", "button", "iframe"]):
    #             element.decompose()
    #         main_content = soup.find('main') or soup.find('article') or soup.body
    #         text = main_content.get_text(separator='\n', strip=True) if main_content else ""
    #         cleaned_text = "\n".join(line for line in text.splitlines() if line.strip())

    #         logger.info(f"Dynamic scrape successful for {url}. Content length: {len(cleaned_text)}")
    #         return cleaned_text[:20000]

    # except playwright.async_api.Error as e:
    #     logger.error(f"Playwright error during dynamic scrape of {url}: {e}", exc_info=True)
    #     logger.info(f"Falling back to static scrape for {url} after Playwright error.")
    #     return await scrape_url_content_static(url, timeout=timeout)
    # except Exception as e:
    #     logger.error(f"Unexpected error during dynamic scrape of {url}: {e}", exc_info=True)
    #     logger.info(f"Falling back to static scrape for {url} after unexpected error.")
    #     return await scrape_url_content_static(url, timeout=timeout)
    # --- End Playwright Example ---

    # If BROWSER_AUTOMATION_ENABLED is True but Playwright/Selenium logic isn't fully implemented yet
    logger.warning("Dynamic scraping logic is incomplete. Falling back to static scrape.")
    return await scrape_url_content_static(url, timeout=timeout)


async def find_trigger_events(max_sources: int = 5) -> List[Dict[str, Any]]:
    """
    Scrapes predefined news/social sources to find potential trigger events.
    Uses static scraping primarily, falls back if needed.
    """
    logger.info("Searching for trigger events...")
    # Define diverse sources (RSS, news homepages, specific X.com searches/lists if API available)
    # Use reliable, frequently updated sources relevant to target industries/countries
    sources = [
        "https://techcrunch.com/",
        "https://www.wsj.com/news/markets", # Paywalled, might only get headlines
        "https://www.bloomberg.com/markets", # Paywalled
        "https://news.google.com/rss/search?q=startup+funding+OR+acquisition+OR+layoffs+OR+%22major+partnership%22+in+US+OR+UK+OR+DE+OR+CA+OR+AU&hl=en-US&gl=US&ceid=US%3Aen", # Google News RSS
        "https://news.ycombinator.com/news", # Hacker News
        # Add more specific industry news sites (e.g., Fierce Pharma, The Banker)
    ]
    random.shuffle(sources) # Process sources in random order each time

    trigger_keywords = ["launch", "acquire", "funding", "partnership", "crisis", "outage", "layoff", "regulatory", "disruption", "competitor", "pivot", "expansion", "restructuring"]
    potential_events = []
    processed_count = 0

    scrape_tasks = []
    for source_url in sources[:max_sources]: # Limit number of sources per cycle
        # Use static scrape first as it's cheaper/faster
        scrape_tasks.append(scrape_url_content_static(source_url))

    results = await asyncio.gather(*scrape_tasks, return_exceptions=True)

    for i, result in enumerate(results):
        source_url = sources[i]
        if isinstance(result, Exception):
            logger.warning(f"Scraping failed for source {source_url}: {result}")
            continue
        if isinstance(result, str) and result:
            content = result.lower() # Search in lowercase
            found_keywords = [kw for kw in trigger_keywords if kw in content]
            if found_keywords:
                logger.info(f"Potential trigger keywords {found_keywords} found in: {source_url}")
                # Add event with snippet - AI will analyze context later
                potential_events.append({
                    "source": source_url,
                    "content_snippet": result[:1000] + "..." # Provide a decent snippet
                })
                processed_count += 1

    logger.info(f"Found {len(potential_events)} potential trigger events from {processed_count} sources.")
    return potential_events

# --- Placeholder for finding contact info ---
# This requires sophisticated techniques and is legally sensitive.
async def find_contact_email(company_name: str, role: Optional[str]) -> Optional[str]:
     logger.warning(f"Contact email lookup for {company_name} ({role}) is not implemented.")
     # 1. Use search engines (Google Dorking)
     # 2. Check company website (Contact/Team pages) - requires scraping
     # 3. Use hypothesis patterns (e.g., f.last@company.com) - unreliable
     # 4. Check LinkedIn (requires login/API or careful public scraping)
     # 5. Use paid lookup tools (Apollo, Hunter - outside budget)
     return None