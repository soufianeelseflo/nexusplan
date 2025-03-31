# backend/app/api/api_v1/endpoints/webhooks.py
from fastapi import APIRouter, Request, Header, HTTPException, BackgroundTasks, Depends, Response
from app.core.config import settings
from app.services import payment_service # Service layer dependency
# Import Pydantic models for webhook payload validation
from app.models.webhook_models import LemonSqueezyWebhookPayload
import hmac
import hashlib
import json
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

# Dependency for verifying Lemon Squeezy signature
async def verify_lemonsqueezy_signature(request: Request, x_signature: str = Header(None)):
    """Verifies the webhook signature from Lemon Squeezy using HMAC-SHA256."""
    if not x_signature:
        logger.error("Webhook received without X-Signature header.")
        raise HTTPException(status_code=401, detail="Missing webhook signature.")
    if not settings.LEMONSQUEEZY_WEBHOOK_SECRET:
        logger.critical("LEMONSQUEEZY_WEBHOOK_SECRET is not configured. Cannot verify webhook signature.")
        raise HTTPException(status_code=500, detail="Webhook processing configuration error.")

    raw_body = await request.body()
    try:
        # Calculate the expected signature
        computed_hash = hmac.new(
            settings.LEMONSQUEEZY_WEBHOOK_SECRET.encode(settings.ENCODING),
            raw_body,
            hashlib.sha256
        ).hexdigest()

        # Securely compare the computed hash with the received signature
        if not hmac.compare_digest(computed_hash, x_signature):
            logger.warning(f"Invalid webhook signature. Computed: {computed_hash}, Received: {x_signature}")
            raise HTTPException(status_code=401, detail="Invalid webhook signature.")

        logger.info("Webhook signature verified successfully.")
        # Return the raw body only if verification passes
        return raw_body
    except Exception as e:
        logger.error(f"Webhook signature verification failed: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail="Webhook signature verification error.")


@router.post("/lemonsqueezy", status_code=202) # Respond with 202 Accepted quickly
async def handle_lemonsqueezy_webhook(
    background_tasks: BackgroundTasks,
    raw_body: bytes = Depends(verify_lemonsqueezy_signature) # Verify signature first
):
    """
    Handles incoming webhooks from Lemon Squeezy.
    Verifies signature, validates payload, and processes relevant events in the background.
    Responds quickly with 202 Accepted.
    """
    try:
        # Decode and parse the JSON payload
        payload_dict = json.loads(raw_body.decode(settings.ENCODING))

        # Validate payload structure using Pydantic model
        try:
            webhook_payload = LemonSqueezyWebhookPayload(**payload_dict)
        except Exception as pydantic_error: # Catch Pydantic validation errors
            logger.error(f"Webhook payload validation failed: {pydantic_error}", exc_info=True)
            # Log the problematic payload structure if possible (be careful with sensitive data)
            # logger.debug(f"Invalid payload structure: {payload_dict}")
            raise HTTPException(status_code=422, detail=f"Webhook payload validation error: {pydantic_error}")

        event_name = webhook_payload.meta.event_name
        order_data = webhook_payload.data # Now validated data

        logger.info(f"Processing verified Lemon Squeezy Webhook. Event: {event_name}, Order ID: {order_data.id if order_data else 'N/A'}")

        # --- Process Specific Events ---
        # Focus on events indicating successful payment completion
        # Check Lemon Squeezy docs for the exact event name for a completed order/payment
        # Common events might be 'order_created' (check status), 'order_paid', 'subscription_payment_success'
        if event_name == "order_created" and order_data and order_data.attributes.status == "paid":
            logger.info(f"Order {order_data.id} created and paid. Scheduling fulfillment.")
            # Add the fulfillment task to run in the background
            background_tasks.add_task(payment_service.handle_successful_payment, order_data.model_dump()) # Pass validated data dict
        elif event_name == "order_paid": # Hypothetical event name - check docs
             logger.info(f"Order {order_data.id} paid. Scheduling fulfillment.")
             background_tasks.add_task(payment_service.handle_successful_payment, order_data.model_dump())
        # Add other relevant event handlers here
        # elif event_name == "subscription_created":
        #     background_tasks.add_task(payment_service.handle_subscription_created, order_data.model_dump())
        else:
            logger.info(f"Webhook event '{event_name}' received but not configured for processing.")

        # Acknowledge receipt immediately
        return {"status": "Webhook received and processing initiated"}

    except json.JSONDecodeError:
        logger.error("Invalid JSON received in webhook body.")
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")
    except HTTPException as http_exc:
        # Re-raise HTTPExceptions (like signature verification failure)
        raise http_exc
    except Exception as e:
        logger.error(f"Unexpected error processing webhook payload: {e}", exc_info=True)
        # Return a generic server error, but acknowledge receipt if possible
        # Avoid sending detailed internal errors back to the webhook sender
        return Response(status_code=500, content="Internal server error processing webhook.")