    # backend/app/services/analysis_service.py
from app.core.config import settings
from app.services.openrouter_service import generate_with_openrouter
from app.services.scraping_service import scrape_url_content, scrape_dynamic_content # Assuming these exist
from app.services.cache_service import async_memory_cache
from typing import List, Dict, Any, Optional
import logging
import json

logger = logging.getLogger(__name__)

@async_memory_cache(ttl=settings.CACHE_TTL_SECONDS) # Cache analysis results
async def analyze_trigger_event_and_identify_targets(trigger_event: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Analyzes a trigger event using AI and identifies potential target companies/people.
    Returns a list of target dictionaries.
    """
    logger.info(f"Analyzing trigger event from source: {trigger_event.get('source', 'N/A')}")
    content_snippet = trigger_event.get('content_snippet', '')
    if not content_snippet:
        logger.warning("Trigger event has no content snippet for analysis.")
        return []

    # Construct a detailed prompt for target identification
    prompt = f"""
    Analyze the following trigger event context scraped from {trigger_event.get('source', 'unknown source')}:
    --- START CONTEXT ---
    {content_snippet}
    --- END CONTEXT ---

    Based *only* on this context and general knowledge:
    1. Identify up to 5 specific companies that are most likely directly affected by, involved in, or represent a key opportunity related to this event.
    2. For each company, if possible from the context or common knowledge, identify a likely relevant decision-maker role (e.g., CEO, CMO, Head of Sales, VP Eng).
    3. Briefly state the potential immediate need or pain point this event might create for each identified company (1 sentence max).
    4. Filter results to companies likely based in or heavily operating within {', '.join(settings.TARGET_COUNTRIES)} and primarily within industries: {', '.join(settings.TARGET_INDUSTRIES)}.

    Format the output STRICTLY as a JSON list of objects. Each object must have keys: "company_name", "decision_maker_role" (or null), "potential_need".
    Example: [{"company_name": "ExampleCorp", "decision_maker_role": "CEO", "potential_need": "Needs rapid competitor response analysis."}, ...]
    If no relevant companies are identified, return an empty list [].
    """

    try:
        # Use a balanced model for this analysis task
        analysis_result_str = await generate_with_openrouter(
            prompt=prompt,
            model_preference="balanced",
            max_tokens=500 # Adjust as needed
        )

        # Attempt to parse the JSON output from the AI
        try:
            targets = json.loads(analysis_result_str)
            if not isinstance(targets, list):
                logger.warning(f"AI target analysis did not return a valid list: {analysis_result_str}")
                return []
            # Basic validation of list items
            validated_targets = []
            for target in targets:
                if isinstance(target, dict) and "company_name" in target and "potential_need" in target:
                    validated_targets.append({
                        "company_name": target.get("company_name"),
                        "decision_maker_role": target.get("decision_maker_role"), # Can be None
                        "potential_need": target.get("potential_need"),
                        "trigger_context": content_snippet[:500] # Add context for outreach
                    })
                else:
                    logger.warning(f"Skipping invalid target format in AI response: {target}")

            logger.info(f"AI identified {len(validated_targets)} potential targets from trigger.")
            return validated_targets

        except json.JSONDecodeError:
            logger.error(f"Failed to decode JSON response from AI target analysis: {analysis_result_str}", exc_info=True)
            return []
        except Exception as parse_err:
             logger.error(f"Error processing AI target analysis result: {parse_err}", exc_info=True)
             return []

    except Exception as e:
        logger.error(f"Error during AI trigger analysis: {e}", exc_info=True)
        return []


@async_memory_cache(ttl=settings.CACHE_TTL_SECONDS * 2) # Cache longer
async def enrich_target_data(target: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enriches target data by attempting to find contact info and recent activity.
    This is a placeholder for complex scraping/lookup logic.
    """
    logger.info(f"Attempting to enrich data for target: {target.get('company_name')}")
    enriched_target = target.copy()

    # --- Placeholder for Advanced Scraping/Lookup ---
    # In a real system, this would involve:
    # 1. Searching LinkedIn/Company Website/News for the decision maker's name and role.
    # 2. Using tools or techniques (like Hunter.io patterns, public directory scraping) to *infer* or find a business email. HIGHLY complex and legally sensitive.
    # 3. Scraping recent company news or the decision maker's X.com/LinkedIn activity.

    # For now, we simulate finding basic info and construct a test email
    # Replace this with actual scraping logic using scraping_service functions
    # email_found = await scraping_service.find_contact_email(target['company_name'], target.get('decision_maker_role'))
    # recent_activity_summary = await scraping_service.scrape_recent_activity(target['company_name'], target.get('decision_maker_role'))

    # Using placeholder data for demonstration flow
    email_found = f"test.contact+{target.get('company_name','unknown').replace(' ','').lower()}@example.com" # Use a test domain
    recent_activity_summary = f"Recent focus on {random.choice(['growth', 'efficiency', 'innovation'])} within {target.get('company_name', 'the company')}."

    enriched_target["email"] = email_found # Can be None if not found
    enriched_target["activity"] = recent_activity_summary # Can be None

    logger.info(f"Enrichment result for {target.get('company_name')}: Email {'Found' if email_found else 'Not Found'}")
    return enriched_target


@async_memory_cache(ttl=settings.CACHE_TTL_SECONDS)
async def generate_report_insight(trigger_context: str, target_info: Dict[str, Any]) -> str:
    """
    Generates a unique, concise micro-insight for outreach using AI.
    """
    logger.info(f"Generating micro-insight for {target_info.get('company_name')}")
    company = target_info.get("company_name", "the company")
    role = target_info.get("role", "their role")

    prompt = f"""
    Analyze this trigger event context: '{trigger_context}'
    And this target information: Company '{company}', Role '{role}'.

    Generate exactly ONE concise, non-obvious, thought-provoking insight or question (max 20 words) directly relevant to the target's likely perspective on the trigger event. This insight will be used in outreach to demonstrate immediate value. Avoid generic statements. Focus on a potential implication, risk, or opportunity.

    Example Insight: Given the recent market shift, how quickly can {company} adapt its supply chain?
    Example Insight: Does {company}'s current strategy account for the competitor's latest move in the AI space?

    Output ONLY the single insight/question.
    """
    try:
        # Use a fast model for this specific, short generation task
        insight = await generate_with_openrouter(
            prompt=prompt,
            model_preference="flash", # Use the fastest model preference
            max_tokens=60,
            temperature=0.8 # Slightly higher temp for creativity
        )
        logger.info(f"Generated micro-insight: {insight}")
        return insight
    except Exception as e:
        logger.error(f"Error generating micro-insight: {e}", exc_info=True)
        return f"How does the recent event impact {company}'s key objectives?" # Fallback insight


async def generate_full_report_content(order_data: Dict[str, Any], trigger_context: Optional[str] = None) -> Dict[str, Any]:
    """
    Generates the full content for the intelligence report using AI.
    """
    product_name = order_data.get("attributes", {}).get("first_order_item", {}).get("product_name", "Intelligence Report")
    client_company = order_data.get("attributes", {}).get("user_name", "Client Company") # Assuming user_name might be company
    order_id = order_data.get("id", "N/A")

    logger.info(f"Generating content for report '{product_name}' (Order: {order_id}) for {client_company}")

    # --- Gather necessary context ---
    # Ideally, link trigger context or analysis data gathered during outreach to the order
    # For now, use placeholder context or re-analyze if needed
    if not trigger_context:
        trigger_context = f"Context related to the order for {client_company} regarding {product_name}." # Basic fallback

    # --- Construct detailed prompt for report generation ---
    prompt = f"""
    Act as a Tier-1 Management Consultant and Market Analyst AI. Generate a comprehensive, actionable intelligence report titled '{product_name}' for '{client_company}'.

    Base the report on the following context (trigger event, initial analysis, etc.):
    --- START CONTEXT ---
    {trigger_context}
    --- END CONTEXT ---

    The report MUST include the following sections:
    1.  **Executive Summary:** A concise overview (2-3 paragraphs) summarizing the key findings and primary recommendations.
    2.  **Situation Analysis:** Detailed analysis of the trigger event or market situation, its immediate implications, and potential impact on {client_company}. Use synthesized data and logical reasoning.
    3.  **Competitor/Market Landscape (If Applicable):** Analysis of key competitors' likely reactions or relevant market dynamics.
    4.  **Risk Assessment:** Identification of the top 3-5 critical risks for {client_company} arising from this situation.
    5.  **Strategic Recommendations:** Provide 3-5 clear, actionable, and prioritized recommendations for {client_company} to navigate the situation, mitigate risks, or capitalize on opportunities. Justify each recommendation.

    Ensure the tone is professional, authoritative, and data-driven (even if simulating data synthesis). Structure the output clearly with markdown headings for each section. The total length should be substantial enough to justify the premium price point (approx 1000-2000 words).
    """

    try:
        # Use a high-quality model for the final report content
        report_text = await generate_with_openrouter(
            prompt=prompt,
            model_preference="high_quality", # Use best available model
            max_tokens=3000, # Allow for longer report content
            temperature=0.6 # Lower temp for more factual tone
        )
        logger.info(f"Successfully generated report content for Order: {order_id}")

        # --- Parse the generated text into sections ---
        # Basic parsing based on expected markdown headings - improve with regex if needed
        sections_dict = {}
        current_section = "introduction" # Default if no heading found first
        sections_dict[current_section] = ""

        lines = report_text.split('\n')
        for line in lines:
            line_stripped = line.strip()
            if line_stripped.startswith("## ") or line_stripped.startswith("**1. Executive Summary**") or line_stripped.startswith("**Executive Summary:**"):
                current_section = "executive_summary"
                sections_dict[current_section] = ""
            elif line_stripped.startswith("## ") or line_stripped.startswith("**2. Situation Analysis**") or line_stripped.startswith("**Situation Analysis:**"):
                current_section = "situation_analysis"
                sections_dict[current_section] = ""
            elif line_stripped.startswith("## ") or line_stripped.startswith("**3. Competitor/Market Landscape**") or line_stripped.startswith("**Competitor/Market Landscape:**"):
                current_section = "landscape"
                sections_dict[current_section] = ""
            elif line_stripped.startswith("## ") or line_stripped.startswith("**4. Risk Assessment**") or line_stripped.startswith("**Risk Assessment:**"):
                current_section = "risk_assessment"
                sections_dict[current_section] = ""
            elif line_stripped.startswith("## ") or line_stripped.startswith("**5. Strategic Recommendations**") or line_stripped.startswith("**Strategic Recommendations:**"):
                current_section = "recommendations"
                sections_dict[current_section] = ""

            # Append line to current section if it exists
            if current_section in sections_dict:
                 # Add line breaks back, but avoid adding for the heading itself
                 if not (line_stripped.startswith("## ") or line_stripped.startswith("**")):
                     sections_dict[current_section] += line + "\n"


        # Structure for PDF generation
        report_data_for_pdf = {
            "title": product_name,
            "client_name": client_company,
            "executive_summary": sections_dict.get("executive_summary", "Summary not generated.").strip(),
            "sections": [
                {"title": "Situation Analysis", "content": sections_dict.get("situation_analysis", "N/A").strip()},
                {"title": "Competitor/Market Landscape", "content": sections_dict.get("landscape", "N/A").strip()},
                {"title": "Risk Assessment", "content": sections_dict.get("risk_assessment", "N/A").strip()},
                {"title": "Strategic Recommendations", "content": sections_dict.get("recommendations", "N/A").strip()},
            ]
        }
        return report_data_for_pdf

    except Exception as e:
        logger.error(f"Error generating full report content for Order {order_id}: {e}", exc_info=True)
        # Return a dictionary indicating failure, allowing calling function to handle
        return {"error": f"Failed to generate report content: {e}"}