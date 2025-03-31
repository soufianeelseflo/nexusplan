# backend/app/services/outreach_service.py
from app.services.openrouter_service import generate_with_openrouter
from app.services.email_service import send_authenticated_email
from app.services.analysis_service import generate_report_insight # For micro-insight
# Import placeholder for social DM service/logic
# from app.services.social_dm_service import send_direct_message
from app.core.config import settings
from typing import List, Dict, Any
import asyncio
import logging
import random

logger = logging.getLogger(__name__)

async def craft_outreach_message(target_info: Dict[str, Any], trigger_event: Dict[str, Any], service_type: str) -> Dict[str, Any]:
    """
    Uses AI to craft hyper-personalized outreach (email focus primarily).
    Generates subject, body, and includes relevant links.
    """
    logger.info(f"Crafting outreach message for {target_info.get('company_name')} regarding trigger: {trigger_event.get('source', 'N/A')}")

    # Extract relevant details, providing defaults
    name = target_info.get("name", "there")
    company = target_info.get("company_name", "your company")
    role = target_info.get("decision_maker_role", "your role")
    recent_activity = target_info.get("activity", "your company's current focus") # From enrichment
    trigger_context = trigger_event.get("content_snippet", "a recent market development")

    # Determine pricing and links based on service type
    if service_type == "Premium Rapid Report":
        report_price = settings.REPORT_PRICE_PREMIUM
        # Ensure you have separate Lemon Squeezy links for each product
        payment_link = "YOUR_LEMONSQUEEZY_PREMIUM_PRODUCT_LINK" # Replace with actual link
    else: # Default to Standard
        service_type = "Standard Intel Report" # Ensure consistency
        report_price = settings.REPORT_PRICE_STANDARD
        payment_link = "YOUR_LEMONSQUEEZY_STANDARD_PRODUCT_LINK" # Replace with actual link

    website_url = "YOUR_DEPLOYED_WEBSITE_URL" # Replace with actual URL from config or hardcode

    # --- Generate Micro-Insight ---
    try:
        micro_insight = await generate_report_insight(trigger_context, target_info)
    except Exception as insight_err:
        logger.warning(f"Failed to generate micro-insight: {insight_err}. Using fallback.", exc_info=True)
        micro_insight = f"How is {company} positioned regarding the recent developments?" # Generic fallback

    # --- Generate Email Copy ---
    email_prompt = f"""
    Act as an expert B2B outreach strategist specializing in high-value intelligence services. Craft a hyper-personalized, concise (<150 words) cold email to:
    Name: {name}
    Role: {role}
    Company: {company}

    Context: They are likely impacted by/interested in this event: '{trigger_context}'. Their recent known activity/focus: '{recent_activity}'.

    Your Goal: Generate immediate interest in our '{service_type}' priced at ${report_price}, delivered in hours. This report directly addresses the implications of the event context. Drive them to our website or direct payment link.

    Instructions:
    1. Create a compelling, highly personalized subject line referencing the specific event, their company, or role (e.g., "Re: [Event/Competitor] & {company}'s Next Move?" or "Urgent Intel for {name} regarding [Market Shift]"). Max 60 chars if possible.
    2. Write a concise, professional opening acknowledging the specific context or their company's situation relevant to the trigger event. Avoid generic greetings.
    3. Seamlessly integrate this unique micro-insight: '{micro_insight}'
    4. Briefly introduce the '{service_type}' as a rapid, actionable intelligence solution tailored to this specific situation. Emphasize speed ("within hours").
    5. State the price clearly (${report_price}).
    6. Provide clear calls to action: "Learn more on our site: {website_url}" and "Secure your report now (delivery within hours): {payment_link}".
    7. Keep the tone authoritative, insightful, and focused on immediate value. No fluff.
    8. Ensure the output contains ONLY the subject line and the email body, separated by "---BODY---".

    Subject: [Subject Line Here]
    ---BODY---
    [Email Body Here]
    """
    try:
        # Use a balanced model capable of following instructions well
        generated_copy = await generate_with_openrouter(
            prompt=email_prompt,
            model_preference="balanced", # Or high_quality if needed for better nuance
            max_tokens=350 # Allow slightly more room for generation
        )

        # --- Parse Subject and Body ---
        subject = f"Urgent Intel Regarding {company}" # Default subject
        body = f"Dear {name},\n\n[AI failed to generate specific content. Please review context.]" # Default body

        if "---BODY---" in generated_copy:
            parts = generated_copy.split("---BODY---", 1)
            subject_part = parts[0].replace("Subject:", "").strip()
            body_part = parts[1].strip()
            if subject_part:
                subject = subject_part
            if body_part:
                body = body_part
        else:
            logger.warning(f"AI did not follow formatting instructions for email copy. Using defaults/raw output: {generated_copy}")
            # Use the whole output as body if separator is missing
            body = generated_copy.strip()

        return {"subject": subject, "body": body, "payment_link": payment_link, "website_url": website_url}

    except Exception as e:
        logger.error(f"Error generating outreach message for {company}: {e}", exc_info=True)
        # Return default structure on failure
        return {"subject": f"Urgent Intel Regarding {company}", "body": f"Dear {name},\n\nWe noted the recent developments regarding [Event] and wanted to offer our rapid analysis services. Please visit {website_url} for details.", "payment_link": payment_link, "website_url": website_url}


async def execute_outreach_sequence(target_list: List[Dict[str, Any]], trigger_event: Dict[str, Any], service_type: str):
    """
    Iterates through targets, crafts personalized messages, and sends them via primary (email)
    and potentially secondary (DM - placeholder) channels with delays.
    """
    logger.info(f"Starting outreach sequence for {len(target_list)} targets related to trigger: {trigger_event.get('source', 'N/A')}")
    successful_sends = 0
    failed_sends = 0

    for target in target_list:
        target_email = target.get("email")
        target_name = target.get("name", "N/A")
        target_company = target.get("company_name", "N/A")

        if not target_email:
            logger.warning(f"Skipping outreach for {target_name} at {target_company} - No email found during enrichment.")
            # --- Placeholder for Social DM Logic ---
            # if target.get("x_handle") or target.get("linkedin_url"):
            #     logger.info(f"Attempting DM outreach for {target_name}...")
            #     # dm_success = await send_direct_message(target, trigger_event, service_type) # Requires social_dm_service
            #     dm_success = False # Placeholder
            #     if dm_success: logger.info("DM sent.")
            #     else: logger.warning("DM failed.")
            # --- End Placeholder ---
            continue # Move to next target if no email

        logger.info(f"Processing outreach for: {target_name} <{target_email}> at {target_company}")

        try:
            # 1. Craft the personalized message
            message_data = await craft_outreach_message(target, trigger_event, service_type)

            # 2. Send Email via Email Service (includes humanizer call)
            success = await send_authenticated_email(
                to_email=target_email,
                subject=message_data["subject"],
                html_content=message_data["body"].replace('\n', '<br/>') # Convert newlines for HTML email
            )

            if success:
                successful_sends += 1
                logger.info(f"Outreach email successfully sent to {target_email}.")
            else:
                failed_sends += 1
                logger.warning(f"Failed to send outreach email to {target_email} after retries.")
                # Log failure for potential manual review or different strategy

            # 3. Implement Delay Between Sends (CRITICAL for deliverability)
            # Use a longer, more variable delay than the email_service internal delay
            inter_email_delay = random.uniform(45, 120) # Delay 45-120 seconds between *different* recipients
            logger.debug(f"Waiting {inter_email_delay:.1f} seconds before next target outreach...")
            await asyncio.sleep(inter_email_delay)

        except Exception as e:
            failed_sends += 1
            logger.error(f"Unexpected error during outreach processing for {target_email}: {e}", exc_info=True)
            # Wait before processing next target even on error
            await asyncio.sleep(random.uniform(15, 30))

    logger.info(f"Outreach sequence complete. Successful emails: {successful_sends}, Failed emails/targets: {failed_sends}")