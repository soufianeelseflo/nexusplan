# backend/app/models/webhook_models.py
from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, Dict, Any, List
from datetime import datetime

# Define Pydantic models based on Lemon Squeezy webhook payload structure
# Refer to Lemon Squeezy API documentation for the exact structure and field types
# This is a simplified example - adjust based on the actual payload for 'order_created' or 'order_paid'

class LemonSqueezyBaseModel(BaseModel):
    # Use alias for fields that might conflict with Python keywords or have dashes
    # Example: type: str = Field(..., alias='type')
    pass

class MetaData(LemonSqueezyBaseModel):
    event_name: str
    custom_data: Optional[Dict[str, Any]] = None # Adjust if structure is known
    # Add other meta fields if present (e.g., test_mode)
    test_mode: Optional[bool] = None

class StoreAttributes(LemonSqueezyBaseModel):
    name: str
    slug: str
    domain: str
    url: HttpUrl
    # Add other store attributes

class CustomerAttributes(LemonSqueezyBaseModel):
    name: Optional[str] = None
    email: str
    # Add other customer attributes

class OrderItemAttributes(LemonSqueezyBaseModel):
    price_id: int
    product_id: int
    product_name: str
    variant_id: int
    variant_name: str
    quantity: int
    # Add pricing details if needed

class OrderAttributes(LemonSqueezyBaseModel):
    store_id: int
    customer_id: int
    identifier: str # Unique order identifier
    order_number: int
    user_name: Optional[str] = None
    user_email: str
    currency: str
    subtotal: int # In cents
    discount_total: int
    tax: int
    total: int
    status: str # e.g., "pending", "paid", "failed", "refunded"
    receipt_url: Optional[HttpUrl] = None
    created_at: datetime
    updated_at: datetime
    first_order_item: Optional[OrderItemAttributes] = None # Include if nested in payload
    # Add other order attributes

class OrderData(LemonSqueezyBaseModel):
    type: str = Field(..., pattern="^orders$") # Ensure type is 'orders'
    id: str # Order ID (usually numeric string)
    attributes: OrderAttributes
    # Add relationships if needed (e.g., links to customer, store)

# Main Webhook Payload Model
class LemonSqueezyWebhookPayload(LemonSqueezyBaseModel):
    meta: MetaData
    data: OrderData # Assuming the data object is for an order

# Add models for other event types (e.g., SubscriptionData) if needed