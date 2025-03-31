# backend/app/services/automation_service.py
from app.services import (
    scraping_service,
    analysis_service,
    outreach_service,
    token_monitor_service,
    # Import other services as needed
)
from app.core.config import settings
import asyncio
import logging
import random

logger = logging.getLogger(__name__)

# --- Main Orchestration Cycle ---
async def run_main_cycle():
    """
    The core autonomous loop: finds triggers, analyzes, enriches, and initiates outreach.
    Triggered by the scheduler in main.py.
    """
    logger.info("--- Starting New Automation Cycle ---")

    # Check budget before starting
    if token_monitor_service.get_remaining_budget() <= settings.TOKEN_BUDGET_WARN_THRESHOLD / 2: # Use a lower threshold to stop cycle
        logger.warning("Token budget critically low. Skipping automation cycle.")
        # Optionally send another alert
        # await token_monitor_service.send_telegram_alert("Automation cycle skipped due to critically low budget.")
        return

    try:
        # 1. Find Potential Trigger Events
        # Limit the number processed per cycle to manage load/cost
        potential_triggers = await scraping_service.find_trigger_events()
        if not potential_triggers:
            logger.info("No significant trigger events found in this cycle.")
            return

        # Process a limited number of triggers per cycle
        triggers_to_process = potential_triggers[:settings.MAX_CONCURRENT_TASKS]
        logger.info(f"Found {len(potential_triggers)} potential triggers. Processing up to {len(triggers_to_process)}.")

        tasks = []
        for trigger in triggers_to_process:
            # Create an async task for each trigger to process concurrently
            tasks.append(asyncio.create_task(process_single_trigger(trigger)))

        # Wait for all trigger processing tasks to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Log results/errors from concurrent processing
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Error processing trigger {i+1}: {result}", exc_info=result)
            else:
                logger.info(f"Successfully processed trigger {i+1}.")

    except Exception as e:
        logger.error(f"Critical error during automation cycle: {e}", exc_info=True)
        await token_monitor_service.send_telegram_alert(f"CRITICAL ERROR in automation cycle: {e}")

    logger.info("--- Automation Cycle Finished ---")


async def process_single_trigger(trigger_event: dict):
    """Processes a single trigger event: analyze, enrich, outreach."""
    logger.info(f"Processing trigger from: {trigger_event.get('source', 'N/A')}")

    # 2. Analyze Trigger & Identify Targets
    targets = await analysis_service.analyze_trigger_event_and_identify_targets(trigger_event)
    if not targets:
        logger.info("No relevant targets identified for this trigger.")
        return

    logger.info(f"Identified {len(targets)} potential targets. Proceeding with enrichment.")

    # 3. Enrich Target Data (Concurrently if possible)
    enrichment_tasks = [analysis_service.enrich_target_data(t) for t in targets]
    enriched_targets_results = await asyncio.gather(*enrichment_tasks, return_exceptions=True)

    valid_targets_for_outreach = []
    for i, result in enumerate(enriched_targets_results):
        if isinstance(result, Exception):
            logger.error(f"Error enriching target {targets[i].get('company_name', 'N/A')}: {result}", exc_info=result)
        elif isinstance(result, dict) and result.get("email"): # Check if enrichment was successful and email found
            valid_targets_for_outreach.append(result)
        else:
             logger.warning(f"Enrichment failed or no email found for target {targets[i].get('company_name', 'N/A')}")

    if not valid_targets_for_outreach:
        logger.info("No valid targets with contact info after enrichment.")
        return

    logger.info(f"Successfully enriched {len(valid_targets_for_outreach)} targets. Initiating outreach.")

    # 4. Execute Outreach Sequence
    # Determine service type - could be based on trigger analysis or default
    service_type = "Premium Rapid Report" # Default to premium for higher potential return
    try:
        await outreach_service.execute_outreach_sequence(
            target_list=valid_targets_for_outreach,
            trigger_event=trigger_event,
            service_type=service_type
        )
        logger.info(f"Outreach sequence initiated for trigger: {trigger_event.get('source', 'N/A')}")
    except Exception as e:
        logger.error(f"Error during outreach execution for trigger {trigger_event.get('source', 'N/A')}: {e}", exc_info=True)


# Note: Fulfillment logic is triggered by webhooks via payment_service, not directly in this cycle.
# This service focuses on the proactive part: finding opportunities and initiating contact.