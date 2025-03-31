# backend/app/services/cache_service.py
from cachetools import TTLCache, cached
from cachetools.keys import hashkey # Standard key generator
from functools import wraps
import asyncio
import logging
from app.core.config import settings # Import settings for TTL config

logger = logging.getLogger(__name__)

# --- Centralized Cache Instances ---
# Use TTL defined in settings
# Adjust maxsize based on expected memory usage and number of cached items
default_cache = TTLCache(maxsize=2048, ttl=settings.CACHE_TTL_SECONDS)
# Potentially define other caches with different TTLs if needed
# short_term_cache = TTLCache(maxsize=512, ttl=600) # Example: 10 min TTL

# --- Async Cache Decorator ---
def async_ttl_cache(cache_instance=default_cache):
    """
    Decorator to cache the results of an async function using cachetools.TTLCache.
    Handles async function caching correctly.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Create a cache key based on function and arguments
            # Using hashkey ensures complex arguments are handled
            key = hashkey(func.__name__, *args, **kwargs)

            try:
                # Check cache first
                result = cache_instance[key]
                logger.debug(f"CACHE HIT: Function '{func.__name__}' Key: '{key}'")
                return result
            except KeyError:
                # Cache miss - execute the function
                logger.debug(f"CACHE MISS: Function '{func.__name__}' Key: '{key}'")
                result = await func(*args, **kwargs)
                # Store the result in the cache
                try:
                    cache_instance[key] = result
                except ValueError:
                    logger.warning(f"Failed to cache result for {func.__name__} - value might be too large for cache.", exc_info=True)
                return result
            except Exception as e:
                 logger.error(f"Error during cache lookup/store for {func.__name__}: {e}", exc_info=True)
                 # Execute function without caching on error
                 return await func(*args, **kwargs)
        return wrapper
    return decorator

# --- Cache Management Functions ---
def clear_cache(cache_instance=default_cache):
    """Clears a specific cache instance."""
    try:
        count = len(cache_instance)
        cache_instance.clear()
        logger.info(f"Cache instance cleared successfully. Removed {count} items.")
    except Exception as e:
        logger.error(f"Error clearing cache instance: {e}", exc_info=True)

def clear_all_known_caches():
    """Clears all defined cache instances."""
    logger.info("Clearing all known caches...")
    clear_cache(default_cache)
    # clear_cache(short_term_cache) # Clear others if defined
    logger.info("All known caches cleared.")

def get_cache_stats(cache_instance=default_cache) -> dict:
    """Returns statistics for a specific cache instance."""
    try:
        return {
            "maxsize": cache_instance.maxsize,
            "current_size": cache_instance.currsize,
            "ttl": getattr(cache_instance, 'ttl', 'N/A') # TTLCache has ttl
        }
    except Exception as e:
        logger.error(f"Error getting cache stats: {e}", exc_info=True)
        return {}

# Example Usage (apply decorator to service functions):
# from app.services.cache_service import async_ttl_cache
#
# @async_ttl_cache() # Uses default_cache with TTL from settings
# async def some_expensive_io_call(param1: str):
#     # ... function logic ...
#     pass
#
# @async_ttl_cache(cache_instance=short_term_cache) # Use a different cache
# async def another_call(arg1):
#     # ... function logic ...
#     pass