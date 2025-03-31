# backend/app/api/api_v1/endpoints/voice.py
from fastapi import APIRouter, Request, Response, Form, Query, Depends, HTTPException
from twilio.twiml.voice_response import VoiceResponse
from app.services import voice_agent_service # Service layer dependency
from typing import Optional
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

# Dependency to reliably extract CallSid from Twilio webhook requests
async def get_call_sid_from_request(request: Request) -> str:
    form_data = await request.form()
    call_sid = form_data.get("CallSid")
    if not call_sid:
        # Twilio might send it differently in some cases, check headers or query params as fallback if needed
        call_sid = request.query_params.get("call_sid") # Check query param as used in Gather action URL
        if not call_sid:
            logger.error("CallSid could not be extracted from request form data or query parameters.")
            raise HTTPException(status_code=400, detail="CallSid missing from Twilio request")
    return call_sid

@router.post("/incoming_call", response_class=Response)
async def handle_incoming_call(request: Request, call_sid: str = Depends(get_call_sid_from_request)):
    """
    Handles the initial webhook from Twilio when a call connects.
    Initiates the conversation flow via the voice_agent_service.
    """
    logger.info(f"Handling incoming call. CallSid: {call_sid}")
    try:
        # Delegate the logic to the service layer, passing the CallSid for session context
        response_twiml_str: str = await voice_agent_service.handle_initial_call(call_sid)
        # Return the TwiML response to Twilio
        return Response(content=response_twiml_str, media_type="application/xml")
    except Exception as e:
        logger.error(f"Error processing incoming call {call_sid}: {e}", exc_info=True)
        # Generate a safe TwiML error response
        response = VoiceResponse()
        response.say("We apologize, but an error occurred connecting your call. Please try again later.", voice='Polly.Joanna-Neural')
        response.hangup()
        return Response(content=str(response), media_type="application/xml", status_code=500)

@router.post("/respond", response_class=Response)
async def handle_response(
    request: Request, # Keep request for potential future header/body inspection
    call_sid: str = Depends(get_call_sid_from_request), # Get CallSid via dependency
    SpeechResult: Optional[str] = Form(None), # Result from <Gather input="speech">
    Digits: Optional[str] = Form(None) # Result from <Gather input="dtmf">
):
    """
    Handles the webhook from Twilio after a <Gather> verb completes.
    Processes user speech or digit input via the voice_agent_service.
    """
    user_input = SpeechResult if SpeechResult is not None else Digits
    logger.info(f"Handling response for CallSid: {call_sid}. User Input: '{user_input}' (Type: {'Speech' if SpeechResult else 'Digits' if Digits else 'Timeout/None'})")

    try:
        # Delegate processing to the service layer
        response_twiml_str: str = await voice_agent_service.handle_subsequent_input(
            call_sid=call_sid,
            user_input=user_input # Pass None if gather timed out
        )
        # Return the next TwiML instructions to Twilio
        return Response(content=response_twiml_str, media_type="application/xml")
    except Exception as e:
        logger.error(f"Error processing response for call {call_sid}: {e}", exc_info=True)
        # Generate a safe TwiML error response
        response = VoiceResponse()
        response.say("An internal system error occurred. Please hang up and try your call again.", voice='Polly.Joanna-Neural')
        response.hangup()
        return Response(content=str(response), media_type="application/xml", status_code=500)