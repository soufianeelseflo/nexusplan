# backend/app/services/payment_service.py
import logging
import asyncio
from app.services import analysis_service, report_service, email_service, token_monitor_service
from app.core.config import settings
from typing import Dict, Any

logger = logging.getLogger(__name__)

async def handle_successful_payment(order_data: Dict[str, Any]):
    """
    Handles the entire fulfillment process triggered by a successful payment webhook.
    This function is designed to be run as a background task.
    """
    order_id = order_data.get("id", "N/A")
    client_email = order_data.get("attributes", {}).get("user_email")
    product_name = order_data.get("attributes", {}).get("first_order_item", {}).get("product_name", "Intelligence Report")
    client_name = order_data.get("attributes", {}).get("user_name", client_email) # Use email as fallback name

    logger.info(f"Starting fulfillment process for Order ID: {order_id}, Product: '{product_name}', Client: {client_email}")

    if not client_email:
        logger.error(f"Cannot fulfill Order ID: {order_id}. Client email is missing in webhook data.")
        await token_monitor_service.send_telegram_alert(f"CRITICAL: Fulfillment failed for Order {order_id}. Client email missing!")
        return # Cannot proceed without recipient email

    try:
        # --- Step 1: Generate Report Content using AI ---
        # Ideally, context related to the trigger/analysis that led to this sale
        # should be retrieved here (e.g., from a database keyed by order details or product ID).
        # For now, we pass minimal context. Enhance this by storing initial analysis data.
        trigger_context_placeholder = f"Context for order {order_id} regarding {product_name} for {client_name}."
        logger.info(f"Generating report content for Order ID: {order_id}...")
        report_content_data = await analysis_service.generate_full_report_content(order_data, trigger_context_placeholder)

        if "error" in report_content_data:
            # Handle error during content generation
            error_message = report_content_data["error"]
            logger.error(f"Failed to generate report content for Order ID: {order_id}. Error: {error_message}")
            await token_monitor_service.send_telegram_alert(f"ERROR: Report content generation failed for Order {order_id}. Error: {error_message}")
            # Optionally notify client about the delay/issue
            # await email_service.send_authenticated_email(client_email, "Regarding your report order", "There was an issue generating your report, we are looking into it.")
            return # Stop fulfillment

        logger.info(f"Report content generated successfully for Order ID: {order_id}.")

        # --- Step 2: Generate PDF from Content ---
        logger.info(f"Generating PDF report for Order ID: {order_id}...")
        report_filename_base = f"Rapid_Intel_Report_{order_id}_{product_name.replace(' ', '_')}"
        pdf_path = await report_service.generate_pdf_report(report_content_data, report_filename_base)
        logger.info(f"PDF report generated successfully: {pdf_path}")

        # --- Step 3: Deliver Report via Email ---
        logger.info(f"Preparing to email report for Order ID: {order_id} to {client_email}...")
        subject = f"Your '{product_name}' Report from {settings.PROJECT_NAME} is Ready (Order #{order_data.get('attributes',{}).get('order_number', order_id)})"
        body = f"""
        <html><body>
        <p>Dear {client_name},</p>
        <p>Thank you for your purchase (Order #{order_data.get('attributes',{}).get('order_number', order_id)}).</p>
        <p>Please find your requested report, '{product_name}', attached to this email.</p>
        <p>We trust this intelligence will provide significant value to your decision-making process.</p>
        <p>If you have any questions, please reply to this email or contact us at {settings.DOMAIN_EMAIL_USER}.</p>
        <p>Best regards,</p>
        <p>The Team at {settings.PROJECT_NAME}</p>
        </body></html>
        """

        email_success = await email_service.send_authenticated_email(
            to_email=client_email,
            subject=subject,
            html_content=body,
            attachment_path=pdf_path
        )

        if email_success:
            logger.info(f"Report for Order ID: {order_id} successfully delivered to {client_email}.")
            await token_monitor_service.send_telegram_alert(f"SUCCESS: Order {order_id} ({product_name}) fulfilled and report sent to {client_email}.")
        else:
            logger.error(f"Failed to email report for Order ID: {order_id} to {client_email}.")
            await token_monitor_service.send_telegram_alert(f"CRITICAL: Failed to EMAIL report for Order {order_id} to {client_email}! Manual intervention required.")
            # Consider adding to a retry queue or manual follow-up list

    except Exception as e:
        logger.critical(f"CRITICAL ERROR during fulfillment for Order ID: {order_id}. Error: {e}", exc_info=True)
        await token_monitor_service.send_telegram_alert(f"CRITICAL FAILURE during fulfillment for Order {order_id}! Error: {e}. Manual intervention required.")
        # Optionally try to notify client about a general issue
    finally:
        # --- Step 4: Cleanup (Optional) ---
        # Clean up temporary PDF file if it exists and wasn't handled by email service
        if 'pdf_path' in locals() and pdf_path and os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
                logger.info(f"Cleaned up temporary PDF file: {pdf_path}")
            except Exception as cleanup_err:
                logger.warning(f"Failed to clean up temporary PDF {pdf_path}: {cleanup_err}")