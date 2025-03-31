# backend/app/services/analysis_service.py
from app.core.config import settings
from app.services.openrouter_service import generate_with_openrouter
# Import the specific scraping function needed for enrichment
from app.services.scraping_service import find_company_contact_info
from app.services.cache_service import async_ttl_cache
from typing import List, Dict, Any, Optional
import logging
import json
import random # Used only for placeholder enrichment simulation

logger = logging.getLogger(__name__)

# --- Target Identification & Initial Analysis ---
@async_ttl_cache(ttl=settings.CACHE_TTL_SECONDS) # Cache results
async def analyze_trigger_event_and_identify_targets(trigger_event: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Analyzes a trigger event using AI (via OpenRouter) and identifies potential target companies/roles.
    Applies "Think Tool": Validates input, uses specific model, parses robustly.
    Returns a list of validated target dictionaries.
    """
    logger.info(f"Analyzing trigger event from source: {trigger_event.get('source', 'N/A')}")
    content_snippet = trigger_event.get('content_snippet', '')

    # --- Pre-computation Check ---
    if not content_snippet or len(content_snippet) < 50: # Require minimal content
        logger.warning("Trigger event has insufficient content for meaningful analysis.")
        return []

    # --- Construct Prompt with Clear Instructions & Formatting ---
    prompt = f"""
    Analyze the following trigger event context scraped from {trigger_event.get('source', 'unknown source')}:
    --- START CONTEXT ---
    {content_snippet}
    --- END CONTEXT ---

    Based *only* on this context and general business knowledge:
    1. Identify up to {settings.MAX_CONCURRENT_TASKS} specific companies most likely directly affected by, involved in, or representing a key opportunity related to this event.
    2. For each company, infer the most relevant decision-maker role (e.g., CEO, CMO, Head of Sales, VP Eng, Head of Strategy). If unsure, state "Senior Management".
    3. Briefly state the core potential immediate need or pain point this event might create for each identified company (1 concise sentence).
    4. Filter results STRICTLY to companies primarily operating within {', '.join(settings.TARGET_COUNTRIES)} and industries: {', '.join(settings.TARGET_INDUSTRIES)}.

    Format the output STRICTLY as a JSON list of objects. Each object MUST have keys: "company_name" (string), "decision_maker_role" (string or null), "potential_need" (string).
    Example: [{{"company_name": "ExampleCorp", "decision_maker_role": "CEO", "potential_need": "Needs rapid competitor response analysis."}}, ...]
    If no relevant companies matching all criteria are identified, return an empty JSON list []. DO NOT add commentary outside the JSON structure.
    """

    try:
        # Use a reliable, balanced model for structured output
        analysis_result_str = await generate_with_openrouter(
            prompt=prompt,
            model_preference="balanced", # Good balance of capability and cost
            max_tokens=600, # Allow sufficient tokens for JSON list
            temperature=0.5 # Lower temperature for more factual identification
        )

        # --- Input/Output Validation & Robust Parsing ---
        try:
            # Attempt to find JSON within potential AI commentary
            json_start = analysis_result_str.find('[')
            json_end = analysis_result_str.rfind(']') + 1
            if json_start != -1 and json_end != -1:
                json_str = analysis_result_str[json_start:json_end]
                targets = json.loads(json_str)
            else:
                raise json.JSONDecodeError("No valid JSON list found", analysis_result_str, 0)

            if not isinstance(targets, list):
                logger.warning(f"AI target analysis did not return a JSON list: {analysis_result_str}")
                return []

            # Validate structure of each item in the list
            validated_targets = []
            required_keys = {"company_name", "decision_maker_role", "potential_need"}
            for target in targets:
                if isinstance(target, dict) and required_keys.issubset(target.keys()) and isinstance(target["company_name"], str) and isinstance(target["potential_need"], str):
                    # Add trigger context for later use
                    target["trigger_context"] = content_snippet[:1000] # Store relevant context
                    validated_targets.append(target)
                else:
                    logger.warning(f"Skipping invalid target format in AI response: {target}")

            logger.info(f"AI identified {len(validated_targets)} validated potential targets from trigger.")
            return validated_targets

        except json.JSONDecodeError as json_err:
            logger.error(f"Failed to decode JSON response from AI target analysis. Raw response: '{analysis_result_str}'. Error: {json_err}", exc_info=False)
            return []
        except Exception as parse_err:
             logger.error(f"Error processing AI target analysis result: {parse_err}. Raw response: '{analysis_result_str}'", exc_info=True)
             return []

    except ConnectionError as conn_err: # Catch specific error from openrouter_service
        logger.error(f"Connection error during AI trigger analysis: {conn_err}", exc_info=False)
        return [] # Return empty list on connection failure
    except Exception as e:
        logger.error(f"Unexpected error during AI trigger analysis: {e}", exc_info=True)
        return []


# --- Target Enrichment ---
@async_ttl_cache(ttl=settings.CACHE_TTL_SECONDS * 4) # Cache enrichment longer (4 hours)
async def enrich_target_data(target: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enriches target data by finding contact info (email) and recent activity
    using the implemented scraping service.
    Applies "Think Tool": Calls specific enrichment function, handles None results.
    """
    company_name = target.get("company_name")
    role_hint = target.get("decision_maker_role")
    logger.info(f"Enriching data for target: {company_name} (Role hint: {role_hint})")
    enriched_target = target.copy() # Start with existing data

    # --- Pre-computation Check ---
    if not company_name:
        logger.warning("Cannot enrich target data: Company name is missing.")
        enriched_target["email"] = None
        enriched_target["activity"] = "Company name missing for enrichment."
        return enriched_target

    # --- Call Scraping Service for Contact Info ---
    try:
        contact_info = await find_company_contact_info(company_name, role_hint)
        enriched_target["email"] = contact_info.get("email") # Can be None
        enriched_target["name_found"] = contact_info.get("name_found") # Can be None
        enriched_target["role_found"] = contact_info.get("role_found") # Can be None
        logger.info(f"Enrichment result for {company_name}: Email {'Found' if contact_info.get('email') else 'Not Found'}")
    except Exception as e:
        logger.error(f"Error during contact info enrichment for {company_name}: {e}", exc_info=True)
        enriched_target["email"] = None
        enriched_target["name_found"] = None
        enriched_target["role_found"] = None

    # --- Placeholder/Conceptual: Scrape Recent Activity ---
    # This remains complex. A simple approach might be a targeted news search.
    # recent_activity_summary = await scraping_service.scrape_recent_company_news(company_name)
    enriched_target["activity"] = f"Recent strategic focus for {company_name}." # Generic placeholder until implemented

    return enriched_target


# --- Micro-Insight Generation ---
@async_ttl_cache(ttl=settings.CACHE_TTL_SECONDS)
async def generate_report_insight(trigger_context: str, target_info: Dict[str, Any]) -> str:
    """
    Generates a unique, concise micro-insight for outreach using AI (via OpenRouter).
    Applies "Think Tool": Uses fast model, specific prompt, fallback on error.
    """
    company = target_info.get("company_name", "the company")
    role = target_info.get("decision_maker_role", target_info.get("role_found", "Senior Management")) # Use found role if available
    logger.info(f"Generating micro-insight for {company} (Role: {role})")

    # --- Pre-computation Check ---
    if not trigger_context:
        logger.warning("Cannot generate insight: Trigger context is missing.")
        return f"How is {company} adapting to recent market dynamics?" # Generic fallback

    prompt = f"""
    Analyze this trigger event context: '{trigger_context[:1000]}' # Limit context length
    And this target information: Company '{company}', Role '{role}'.

    Generate exactly ONE concise, non-obvious, thought-provoking insight or question (max 25 words) directly relevant to the target's likely perspective on the trigger event. This insight MUST be usable in outreach to demonstrate immediate value and understanding. Avoid generic marketing questions. Focus on a specific potential implication, risk, or strategic opportunity related to the context.

    Output ONLY the single insight/question text. No preamble or explanation.
    """
    try:
        # Use a fast and creative model
        insight = await generate_with_openrouter(
            prompt=prompt,
            model_preference="flash", # Fast and capable
            max_tokens=70,
            temperature=0.75 # Allow some creativity
        )
        # --- Output Validation ---
        if not insight or len(insight) < 10 or len(insight) > 150: # Basic sanity check
             logger.warning(f"Generated insight seems invalid or too generic: '{insight}'. Using fallback.")
             raise ValueError("Generated insight failed validation.")
        logger.info(f"Generated micro-insight: {insight}")
        return insight.strip().replace('"', '') # Clean up output
    except Exception as e:
        logger.error(f"Error generating micro-insight: {e}", exc_info=True)
        # --- Fallback Logic ---
        return f"How might the recent event impact {company}'s Q3 strategic priorities?" # More specific fallback


# --- Full Report Content Generation ---
async def generate_full_report_content(order_data: Dict[str, Any], trigger_context: Optional[str] = None) -> Dict[str, Any]:
    """
    Generates the full content for the intelligence report using AI (via OpenRouter).
    Applies "Think Tool": Uses high-quality model, detailed structured prompt, robust parsing, error handling.
    """
    product_name = order_data.get("attributes", {}).get("first_order_item", {}).get("product_name", "Intelligence Report")
    # Use name if available, else email user part, else "Valued Client"
    client_identifier = order_data.get("attributes", {}).get("user_name") or \
                        order_data.get("attributes", {}).get("user_email", "").split('@')[0] or \
                        "Valued Client"
    order_id = order_data.get("id", "N/A")

    logger.info(f"Generating content for report '{product_name}' (Order: {order_id}) for {client_identifier}")

    # --- Pre-computation Check: Context ---
    # Ideally, retrieve stored context linked to the order_id or product_name
    if not trigger_context:
        trigger_context = f"General market analysis related to {product_name} requested by {client_identifier}."
        logger.warning(f"No specific trigger context found for Order {order_id}. Using generic context.")

    # --- Construct Detailed Prompt ---
    prompt = f"""
    Act as a Tier-1 Management Consultant and Market Analyst AI ({settings.PROJECT_NAME}). Generate a comprehensive, actionable intelligence report titled '{product_name}' for client '{client_identifier}'.

    Base the report *primarily* on the following context:
    --- START CONTEXT ---
    {trigger_context[:4000]} # Limit context size
    --- END CONTEXT ---

    Supplement with general knowledge about {', '.join(settings.TARGET_INDUSTRIES)} and {', '.join(settings.TARGET_COUNTRIES)} as relevant.

    The report MUST include these distinct sections, clearly separated by markdown H2 headings (## Section Title):
    1.  **## Executive Summary:** Concise overview (2-3 paragraphs) of key findings and primary recommendations.
    2.  **## Situation Analysis:** Detailed analysis of the context/trigger event, implications, and potential impact on a company like the client's. Use logical reasoning and synthesize information effectively.
    3.  **## Competitor/Market Landscape:** Analysis of relevant market dynamics or key competitor actions/reactions related to the situation.
    4.  **## Risk Assessment:** Identification and brief explanation of the top 3-5 critical risks arising from this situation.
    5.  **## Strategic Recommendations:** 3-5 clear, actionable, prioritized recommendations for navigating the situation, mitigating risks, or capitalizing on opportunities. Justify each recommendation briefly.

    Adhere to these quality standards:
    - Tone: Professional, authoritative, objective, data-driven (simulate where necessary).
    - Structure: Use ONLY the specified H2 markdown headings. Use bullet points for lists within sections.
    - Length: Aim for approximately 1500-2500 words total. Ensure sufficient depth in each section.
    - Clarity: Write clearly and concisely. Avoid jargon where possible or explain it.
    - Actionability: Recommendations must be concrete and implementable.
    - Uniqueness: Synthesize information, do not just list facts from the context.

    Generate ONLY the report content starting with "## Executive Summary". Do not include a title page or preamble.
    """

    try:
        # Use a high-quality model for comprehensive report generation
        report_text = await generate_with_openrouter(
            prompt=prompt,
            model_preference="high_quality", # e.g., GPT-4 Turbo or Claude 3 Opus
            max_tokens=4000, # Allow ample tokens for generation
            temperature=0.6 # Balance creativity and factual tone
        )
        logger.info(f"Successfully generated raw report content for Order: {order_id}. Length: {len(report_text)}")

        # --- Parse Content into Sections (Robustly) ---
        sections_content = {
            "executive_summary": "Not Generated",
            "situation_analysis": "Not Generated",
            "landscape": "Not Generated",
            "risk_assessment": "Not Generated",
            "recommendations": "Not Generated"
        }
        section_map = {
            "Executive Summary": "executive_summary",
            "Situation Analysis": "situation_analysis",
            "Competitor/Market Landscape": "landscape",
            "Risk Assessment": "risk_assessment",
            "Strategic Recommendations": "recommendations"
        }
        # Split by H2 headings, handling potential variations
        import re
        # Regex to split by '## Title' or '**Title:**' etc., keeping the delimiter part of the next section
        parts = re.split(r'(^##\s+.+?$|^ \*\* \d \. \s+ .+? \*\* :?$)', report_text, flags=re.MULTILINE)

        current_section_key = None
        content_buffer = ""

        for part in parts:
            if not part or part.isspace():
                continue

            part_stripped = part.strip()
            matched_heading = False
            for heading_text, key in section_map.items():
                 # Check for markdown H2 or bolded numbered list patterns
                 if part_stripped.startswith(f"## {heading_text}") or \
                    re.match(rf"^\*\*\d\.\s+{re.escape(heading_text)}\*\*[:]?$", part_stripped):
                    # If we were accumulating content for a previous section, save it
                    if current_section_key:
                        sections_content[current_section_key] = content_buffer.strip()

                    # Start the new section
                    current_section_key = key
                    content_buffer = "" # Reset buffer
                    matched_heading = True
                    break # Found the heading for this part

            if not matched_heading:
                # Append content to the current section's buffer
                content_buffer += part + "\n" # Add newline back

        # Save the content of the last section
        if current_section_key:
            sections_content[current_section_key] = content_buffer.strip()

        # --- Final Validation & Structuring ---
        if sections_content["executive_summary"] == "Not Generated" or sections_content["recommendations"] == "Not Generated":
             logger.warning(f"Report parsing failed to extract key sections for Order {order_id}. Raw text length: {len(report_text)}")
             # Fallback: put all text in summary if parsing fails badly
             if sections_content["executive_summary"] == "Not Generated":
                 sections_content["executive_summary"] = report_text[:3000] # Truncate

        report_data_for_pdf = {
            "title": product_name,
            "client_name": client_identifier,
            "executive_summary": sections_content["executive_summary"],
            "sections": [
                {"title": "Situation Analysis", "content": sections_content["situation_analysis"]},
                {"title": "Competitor/Market Landscape", "content": sections_content["landscape"]},
                {"title": "Risk Assessment", "content": sections_content["risk_assessment"]},
                {"title": "Strategic Recommendations", "content": sections_content["recommendations"]},
            ]
        }
        logger.info(f"Report content successfully parsed into sections for Order: {order_id}")
        return report_data_for_pdf

    except ConnectionError as conn_err:
        logger.error(f"Connection error during report content generation for Order {order_id}: {conn_err}", exc_info=False)
        return {"error": f"AI Connection Error: {conn_err}"}
    except Exception as e:
        logger.error(f"Unexpected error generating full report content for Order {order_id}: {e}", exc_info=True)
        return {"error": f"Failed to generate report content due to internal error: {e}"}