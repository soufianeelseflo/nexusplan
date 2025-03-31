# backend/app/services/automation_service.py
from app.services import (
    scraping_service,
    analysis_service,
    outreach_service,
    token_monitor_service,
    branding_service # Import branding service for scheduling check
)
from app.core.config import settings
import asyncio
import logging
import random
from typing import Dict, Any

logger = logging.getLogger(__name__)

# --- Main Orchestration Cycle ---
async def run_main_cycle():
    """
    The core autonomous loop: finds triggers, analyzes, enriches, and initiates outreach.
    Triggered by the scheduler in main.py. Includes "Think Tool" checks.
    """
    cycle_id = uuid.uuid4().hex[:8] # Unique ID for this cycle run
    logger.info(f"--- Starting Automation Cycle [ID: {cycle_id}] ---")

    # --- Pre-computation Check: Budget ---
    remaining_budget = token_monitor_service.get_remaining_budget()
    # Stop if budget is below half the warning threshold (more conservative)
    if remaining_budget <= settings.TOKEN_BUDGET_WARN_THRESHOLD / 2:
        logger.warning(f"[Cycle {cycle_id}] Token budget critically low (${remaining_budget:.2f}). Skipping automation cycle.")
        # Alert only if budget just dropped below threshold (handled in token_monitor)
        return

    logger.info(f"[Cycle {cycle_id}] Current estimated budget remaining: ${remaining_budget:.2f}")

    try:
        # 1. Find Potential Trigger Events
        logger.info(f"[Cycle {cycle_id}] Searching for trigger events...")
        potential_triggers = await scraping_service.find_trigger_events(max_sources=7) # Increase sources slightly
        if not potential_triggers:
            logger.info(f"[Cycle {cycle_id}] No significant trigger events found.")
            logger.info(f"--- Automation Cycle Finished [ID: {cycle_id}] ---")
            return

        # Process a limited number of triggers concurrently
        triggers_to_process = potential_triggers[:settings.MAX_CONCURRENT_TASKS]
        logger.info(f"[Cycle {cycle_id}] Found {len(potential_triggers)} potential triggers. Processing up to {len(triggers_to_process)} concurrently.")

        # Create and run processing tasks for each trigger
        processing_tasks = [
            asyncio.create_task(process_single_trigger(trigger, cycle_id))
            for trigger in triggers_to_process
        ]
        results = await asyncio.gather(*processing_tasks, return_exceptions=True)

        # Log results/errors from concurrent processing
        successful_triggers = 0
        failed_triggers = 0
        for i, result in enumerate(results):
            trigger_source = triggers_to_process[i].get('source', f'Trigger {i+1}')
            if isinstance(result, Exception):
                failed_triggers += 1
                logger.error(f"[Cycle {cycle_id}] Error processing trigger from {trigger_source}: {result}", exc_info=result)
            elif result is False: # Explicit False return indicates handled failure within process_single_trigger
                failed_triggers += 1
                logger.warning(f"[Cycle {cycle_id}] Handled failure during processing for trigger from {trigger_source}.")
            else: # Assume success if no exception or False
                successful_triggers += 1
                logger.info(f"[Cycle {cycle_id}] Successfully processed trigger from {trigger_source}.")

        logger.info(f"[Cycle {cycle_id}] Trigger processing complete. Success: {successful_triggers}, Failed/Skipped: {failed_triggers}")

    except Exception as e:
        logger.critical(f"[Cycle {cycle_id}] CRITICAL ERROR during automation cycle orchestration: {e}", exc_info=True)
        # Send critical alert
        asyncio.create_task(token_monitor_service.send_telegram_alert(f"CRITICAL ERROR in automation cycle {cycle_id}: {e}"))

    logger.info(f"--- Automation Cycle Finished [ID: {cycle_id}] ---")


async def process_single_trigger(trigger_event: Dict[str, Any], cycle_id: str) -> bool:
    """
    Processes a single trigger event: analyze, enrich, outreach.
    Returns True on successful initiation of outreach, False on handled failure, raises Exception on critical error.
    Includes "Think Tool" checks.
    """
    trigger_source = trigger_event.get('source', 'N/A')
    logger.info(f"[Cycle {cycle_id}] Processing trigger from: {trigger_source}")

    try:
        # 2. Analyze Trigger & Identify Targets ("Think": Validates input/output)
        targets = await analysis_service.analyze_trigger_event_and_identify_targets(trigger_event)
        # --- Verification Step ---
        if not targets:
            logger.info(f"[Cycle {cycle_id}] No relevant targets identified for trigger: {trigger_source}")
            return True # Not an error, just no targets found

        logger.info(f"[Cycle {cycle_id}] Identified {len(targets)} potential targets for {trigger_source}. Proceeding with enrichment.")

        # 3. Enrich Target Data (Concurrently) ("Think": Handles errors)
        enrichment_tasks = [analysis_service.enrich_target_data(t) for t in targets]
        enriched_targets_results = await asyncio.gather(*enrichment_tasks, return_exceptions=True)

        valid_targets_for_outreach = []
        for i, result in enumerate(enriched_targets_results):
            target_company = targets[i].get('company_name', f'Target {i+1}')
            if isinstance(result, Exception):
                logger.error(f"[Cycle {cycle_id}] Error enriching target {target_company}: {result}", exc_info=result)
            elif isinstance(result, dict) and result.get("email"): # CRITICAL: Check for valid email
                valid_targets_for_outreach.append(result)
                logger.info(f"[Cycle {cycle_id}] Successfully enriched target: {target_company} (Email Found)")
            else:
                 logger.warning(f"[Cycle {cycle_id}] Enrichment failed or no email found for target: {target_company}")

        # --- Verification Step ---
        if not valid_targets_for_outreach:
            logger.info(f"[Cycle {cycle_id}] No valid targets with contact info after enrichment for trigger: {trigger_source}")
            return True # Not an error, just no contacts found

        logger.info(f"[Cycle {cycle_id}] Successfully enriched {len(valid_targets_for_outreach)} targets with emails. Initiating outreach for trigger: {trigger_source}")

        # 4. Execute Outreach Sequence ("Think": Handles errors within)
        # Determine service type - default to Premium for max potential value
        service_type = "Premium Rapid Report"
        await outreach_service.execute_outreach_sequence(
            target_list=valid_targets_for_outreach,
            trigger_event=trigger_event,
            service_type=service_type
        )
        # Outreach service logs its own success/failure details internally
        logger.info(f"[Cycle {cycle_id}] Outreach sequence initiated for trigger: {trigger_source}")
        return True # Indicate successful initiation

    except Exception as e:
        logger.error(f"[Cycle {cycle_id}] Unexpected error processing trigger {trigger_source}: {e}", exc_info=True)
        # Don't raise here, allow main loop to log it, return False to indicate handled failure
        return False