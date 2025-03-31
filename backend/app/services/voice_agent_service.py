# backend/app/services/voice_agent_service.py
import asyncio
import logging
import json
import base64
import os
import uuid
import httpx
from typing import Optional, List, Dict, Any

from twilio.twiml.voice_response import VoiceResponse, Gather
from twilio.rest import Client as TwilioClient
from deepgram import (
    DeepgramClient,
    DeepgramClientOptions,
    PrerecordedOptions,
    FileSource
)
from elevenlabs.client import AsyncElevenLabs
from elevenlabs import Voice, VoiceSettings, play

from app.core.config import settings
from app.services.openrouter_service import generate_with_openrouter
from app.services.cache_service import async_ttl_cache, default_cache # Use cache for conversation state
from app.services.token_monitor_service import send_telegram_alert

logger = logging.getLogger(__name__)

# --- Client Initialization ---
twilio_client: Optional[TwilioClient] = None
if settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN:
    try:
        twilio_client = TwilioClient(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        logger.info("Twilio REST client initialized.")
    except Exception as e:
        logger.error(f"Failed to initialize Twilio REST client: {e}", exc_info=True)

deepgram_client: Optional[DeepgramClient] = None
if settings.DEEPGRAM_API_KEY:
    try:
        # More robust Deepgram client config if needed
        # config: DeepgramClientOptions = DeepgramClientOptions(verbose=logging.DEBUG)
        # deepgram_client = DeepgramClient(settings.DEEPGRAM_API_KEY, config)
        deepgram_client = DeepgramClient(settings.DEEPGRAM_API_KEY)
        logger.info("Deepgram client initialized.")
    except Exception as e:
        logger.error(f"Failed to initialize Deepgram client: {e}", exc_info=True)

elevenlabs_client: Optional[AsyncElevenLabs] = None
if settings.ELEVENLABS_API_KEY:
    try:
        elevenlabs_client = AsyncElevenLabs(api_key=settings.ELEVENLABS_API_KEY)
        logger.info("ElevenLabs async client initialized.")
    except Exception as e:
        logger.error(f"Failed to initialize ElevenLabs client: {e}", exc_info=True)

# --- Constants ---
CONVERSATION_CACHE_TTL = 900 # Cache conversation state for 15 minutes
MAX_CONVERSATION_TURNS = 10 # Limit conversation length
AUDIO_TEMP_DIR = "/tmp/phoenix_audio" # Ensure this dir exists or is created

# Create temp audio directory if it doesn't exist
os.makedirs(AUDIO_TEMP_DIR, exist_ok=True)

# --- Helper Functions ---
def _get_conversation_cache_key(call_sid: str) -> str:
    return f"conversation:{call_sid}"

async def _get_conversation_history(call_sid: str) -> List[Dict[str, str]]:
    """Retrieves conversation history from cache."""
    key = _get_conversation_cache_key(call_sid)
    return default_cache.get(key, [])

async def _save_conversation_history(call_sid: str, history: List[Dict[str, str]]):
    """Saves conversation history to cache."""
    key = _get_conversation_cache_key(call_sid)
    # Trim history if it gets too long
    if len(history) > MAX_CONVERSATION_TURNS * 2: # User + Assistant per turn
        history = history[-(MAX_CONVERSATION_TURNS * 2):]
    default_cache[key] = history
    logger.debug(f"Saved conversation history for CallSid: {call_sid}")

@async_ttl_cache(ttl=settings.CACHE_TTL_SECONDS) # Cache synthesized audio files
async def synthesize_speech_elevenlabs(text: str) -> Optional[str]:
    """
    Synthesizes speech using ElevenLabs async client and saves to a temp file.
    Returns the filepath of the generated audio.
    """
    if not elevenlabs_client:
        logger.error("ElevenLabs client not initialized. Cannot synthesize speech.")
        return None
    logger.info(f"Synthesizing speech with ElevenLabs for text: '{text[:50]}...'")
    try:
        audio_iterator = await elevenlabs_client.generate(
            text=text,
            voice=Voice(
                voice_id=settings.ELEVENLABS_VOICE_ID,
                settings=VoiceSettings(stability=0.6, similarity_boost=0.7, style=0.1, use_speaker_boost=True)
            ),
            model='eleven_multilingual_v2' # Or other suitable model
        )

        # Stream audio chunks to a temporary file
        temp_audio_filename = f"{uuid.uuid4()}.mp3"
        temp_audio_filepath = os.path.join(AUDIO_TEMP_DIR, temp_audio_filename)

        with open(temp_audio_filepath, "wb") as f:
            async for chunk in audio_iterator:
                if chunk:
                    f.write(chunk)

        logger.info(f"ElevenLabs TTS successful. Audio saved to: {temp_audio_filepath}")
        return temp_audio_filepath # Return the path to the saved file

    except Exception as e:
        logger.error(f"Error calling ElevenLabs API: {e}", exc_info=True)
        return None

async def _play_audio_via_url(response: VoiceResponse, audio_filepath: str) -> bool:
    """
    Uploads audio to a temporary public URL (requires setup) and uses <Play>.
    This is complex to set up securely.
    """
    logger.warning("_play_audio_via_url requires a mechanism to serve temporary files publicly. Using <Say> as fallback.")
    # 1. Upload audio_filepath to a public temporary storage (e.g., S3 presigned URL, temp web server)
    # 2. Get the public URL
    # 3. response.play(public_url)
    # 4. Schedule cleanup of the temporary file/URL
    return False # Indicate fallback needed

# --- Main Service Functions ---
async def handle_initial_call(call_sid: str) -> str:
    """Handles the initial greeting and gathers the first user input."""
    logger.info(f"Handling initial call setup for CallSid: {call_sid}")
    response = VoiceResponse()
    conversation_history = []

    # Initial greeting
    greeting = f"Thank you for calling {settings.PROJECT_NAME}. How can I assist you with our rapid intelligence reports today?"
    conversation_history.append({"role": "assistant", "content": greeting})

    # Use ElevenLabs TTS if available, otherwise Twilio <Say>
    audio_filepath = await synthesize_speech_elevenlabs(greeting)
    played_custom_audio = False
    # if audio_filepath:
    #     played_custom_audio = await _play_audio_via_url(response, audio_filepath) # Needs public URL setup

    if not played_custom_audio:
        response.say(greeting, voice='Polly.Joanna-Neural') # Use Twilio's TTS as fallback

    # Gather user's first response
    gather = Gather(input='speech', action=f'{settings.API_V1_STR}/voice/respond', # Use relative path or full URL if needed
                    speechTimeout='auto', method='POST', actionOnEmptyResult=True) # actionOnEmptyResult=True ensures webhook fires even on timeout
    response.append(gather)

    # If gather finishes without speech, redirect back to wait for input again (or hang up)
    response.redirect(f'{settings.API_V1_STR}/voice/respond', method='POST') # Loop back to /respond on timeout

    # Save initial state
    await _save_conversation_history(call_sid, conversation_history)

    return str(response)


async def handle_subsequent_input(call_sid: str, user_input: Optional[str]) -> str:
    """Handles user speech/digit input after the initial greeting."""
    logger.info(f"Handling subsequent input for CallSid: {call_sid}. Input: '{user_input}'")
    response = VoiceResponse()
    conversation_history = await _get_conversation_history(call_sid)

    # Handle cases where gather might time out or return empty
    if not user_input:
        logger.info(f"No user input received (timeout or empty). CallSid: {call_sid}")
        # Option 1: Repeat last prompt or ask if they are still there
        reprompt_text = "Sorry, I didn't catch that. Could you please repeat your request?"
        if conversation_history and conversation_history[-1]["role"] == "assistant":
             # Could try repeating last AI statement, but might lead to loops
             pass # Keep reprompt simple for now
        conversation_history.append({"role": "assistant", "content": reprompt_text})
        response.say(reprompt_text, voice='Polly.Joanna-Neural')
    else:
        # Process valid user input
        conversation_history.append({"role": "user", "content": user_input})

        # --- Generate AI Response using OpenRouter/Gemini ---
        # Construct prompt including conversation history for context
        prompt_history = "\n".join([f"{msg['role'].capitalize()}: {msg['content']}" for msg in conversation_history])
        prompt = f"""
        You are a concise and helpful AI sales assistant for {settings.PROJECT_NAME}, a provider of rapid AI-generated intelligence reports ($750 Standard, $1200 Premium).
        Your goal is to answer questions briefly, confirm interest, handle basic objections, and guide the user towards purchasing via the Lemon Squeezy link provided on our website.
        Do not provide the report content itself. Keep responses short (1-3 sentences).

        Conversation History:
        {prompt_history}

        Generate the next assistant response:
        Assistant:
        """
        try:
            ai_response_text = await generate_with_openrouter(
                prompt=prompt,
                model_preference="flash", # Use fast model for conversation
                max_tokens=100, # Keep responses brief
                temperature=0.6
            )
        except Exception as ai_err:
            logger.error(f"AI generation failed for call {call_sid}: {ai_err}", exc_info=True)
            ai_response_text = "I apologize, I'm having trouble processing that request right now. Please visit our website for more information."
            await send_telegram_alert(f"ERROR: Voice AI generation failed for call {call_sid}. Error: {ai_err}")

        conversation_history.append({"role": "assistant", "content": ai_response_text})

        # --- Synthesize Speech ---
        audio_filepath = await synthesize_speech_elevenlabs(ai_response_text)
        played_custom_audio = False
        # if audio_filepath:
        #     played_custom_audio = await _play_audio_via_url(response, audio_filepath)

        if not played_custom_audio:
            response.say(ai_response_text, voice='Polly.Joanna-Neural')

    # --- Continue Gathering Input ---
    # Check if conversation should end (e.g., max turns reached, user hangs up - Twilio handles hangup)
    if len(conversation_history) < MAX_CONVERSATION_TURNS * 2:
        gather = Gather(input='speech', action=f'{settings.API_V1_STR}/voice/respond',
                        speechTimeout='auto', method='POST', actionOnEmptyResult=True)
        response.append(gather)
        response.redirect(f'{settings.API_V1_STR}/voice/respond', method='POST') # Loop back on timeout
    else:
        logger.info(f"Max conversation turns reached for CallSid: {call_sid}. Ending call.")
        final_message = "Thank you for your call. Please visit our website for further details. Goodbye."
        response.say(final_message, voice='Polly.Joanna-Neural')
        response.hangup()
        # Clear conversation history from cache after hangup
        default_cache.pop(_get_conversation_cache_key(call_sid), None)

    # Save updated history
    await _save_conversation_history(call_sid, conversation_history)

    return str(response)

# Note: Deepgram transcription is not explicitly used here as Twilio's <Gather input="speech">
# provides the SpeechResult directly. Deepgram would be used if handling raw audio recordings
# received via Twilio <Record> or other means.