# backend/app/api/api_v1/api.py
from fastapi import APIRouter
from app.api.api_v1.endpoints import voice, webhooks # Import the endpoint routers

# Create the main router for version 1 of the API
api_router_v1 = APIRouter()

# Include the specific endpoint routers with their prefixes and tags for documentation
api_router_v1.include_router(voice.router, prefix="/voice", tags=["Voice Agent Interaction"])
api_router_v1.include_router(webhooks.router, prefix="/webhooks", tags=["Incoming Webhooks"])

# Example: Add a simple health check endpoint within v1 if desired
@api_router_v1.get("/health", tags=["Health Check"])
async def health_check():
    return {"status": "API v1 Operational"}

# If you add more endpoint files (e.g., for admin tasks), import and include them here:
# from app.api.api_v1.endpoints import admin
# api_router_v1.include_router(admin.router, prefix="/admin", tags=["Admin Functions"])