import json
import logging
import os
from datetime import date
from typing import Literal, Optional
from pydantic import BaseModel, Field
from src.retry import retry_with_backoff

logger = logging.getLogger(__name__)

StatusType = Literal["applied", "interview_scheduled", "interviewed", "offer", "rejected", "other"]

CONFIDENCE_THRESHOLD = 0.6

EXTRACTION_PROMPT = """You are extracting structured data from a single email that may or may not relate to a specific job application.

Classify it into exactly one status:
- applied: confirms an application was received
- interview_scheduled: invites, offers, or schedules an interview or an online assessment that has not yet happened
- interviewed: refers to an interview or assessment that has already taken place (past tense, thanking the candidate for their time)
- offer: a job offer was extended
- rejected: the application was declined
- other: anything that is not a direct update on a specific application (job board digests, cold recruiter outreach, unrelated mail)

Also extract, only when explicitly stated in the text:
- location: a specific city or country for the role. Leave null if not stated.
- salary: a figure or range. Only fill this in if status is "offer" and a number is actually given — never guess or infer a salary otherwise.

Return ONLY a JSON object, no markdown fences, no extra text, matching exactly:
{"company": string, "role": string, "status": one of the values above, "event_date": "YYYY-MM-DD" or null, "location": string or null, "salary": string or null, "confidence": float between 0 and 1}

If you are not confident this is a genuine update on a specific application, set status to "other" and confidence below 0.5.
"""

class ExtractedApplication(BaseModel):
    company: str
    role: str
    status: StatusType
    event_date: Optional[date] = None
    location: Optional[str] = None
    salary: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)

def needs_review(extraction: ExtractedApplication) -> bool:
    return extraction.confidence < CONFIDENCE_THRESHOLD or extraction.status == "other"

def _build_user_content(parsed_email: dict) -> str:
    body = parsed_email["body_text"][:3000]

    return (
        f"From: {parsed_email['from']}\n"
        f"Subject: {parsed_email['subject']}\n"
        f"Date: {parsed_email['date']}\n\n"
        f"Body:\n{body}"
    )

def _parse_json_response(text: str) -> dict:
    cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    return json.loads(cleaned)

def _call_gemini(parsed_email: dict) -> dict:
    import google.generativeai as genai

    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    model = genai.GenerativeModel("gemini-3.6-flash")

    @retry_with_backoff()
    def _generate():
        return model.generate_content(
            [EXTRACTION_PROMPT, _build_user_content(parsed_email)],
            generation_config={"response_mime_type": "application/json"},
        )

    return _parse_json_response(_generate().text)

def _call_claude(parsed_email: dict) -> dict:
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    @retry_with_backoff()
    def _generate():
        return client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            system=EXTRACTION_PROMPT,
            messages=[{"role": "user", "content": _build_user_content(parsed_email)}],
        )

    return _parse_json_response(_generate().content[0].text)

def extract_application(parsed_email: dict) -> ExtractedApplication:
    if os.environ.get("GEMINI_API_KEY"):
        raw = _call_gemini(parsed_email)
    elif os.environ.get("ANTHROPIC_API_KEY"):
        raw = _call_claude(parsed_email)
    else:
        raise RuntimeError("Set GEMINI_API_KEY or ANTHROPIC_API_KEY in .env")

    result = ExtractedApplication.model_validate(raw)
    logger.info(
        "Extracted: %s | %s | %s (confidence %.2f)",
        result.company, result.role, result.status, result.confidence,
    )
    if needs_review(result):
        logger.warning("Low-confidence or non-application extraction, flagged for review: %s", parsed_email["subject"])

    return result
