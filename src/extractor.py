import json
import logging
import os
import time
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

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
- rejected: the application was declined. This includes soft or hedged phrasing — "we've decided not to move forward with your application", "not the right match at this time", "we'll keep your profile on file for future opportunities" — these are still rejections even when wrapped in encouraging or relationship-preserving language. Don't let a warm tone override a clear decline.
- other: anything that is not a direct update on a specific application (job board digests, cold recruiter outreach, unrelated mail)

Also extract, only when explicitly stated in the text:
- location: the city only, never the country. If a city is named (even alongside a country, e.g. "Amsterdam, the Netherlands"), extract just the city ("Amsterdam"). If only a country is given with no specific city, leave this null.
- salary: a figure or range. Only fill this in if status is "offer" and a number is actually given — never guess or infer a salary otherwise.

Return ONLY a JSON object, no markdown fences, no extra text, matching exactly:
{"company": string, "role": string, "status": one of the values above, "event_date": "YYYY-MM-DD" or null, "location": string or null, "salary": string or null, "confidence": float between 0 and 1}

Read the email body carefully before deciding on company and role. Job titles and company names are usually stated plainly in a single sentence — "your interest in the position of Junior Data Scientist", "your application for the Marketing Coordinator role at Acme Corp". Use "Unknown" only as a genuine last resort when the text truly gives no indication, never because the answer takes a moment to locate.

If the company or role genuinely cannot be identified from the text, use the string "Unknown" for that field — never return null for company or role.

If you are not confident this is a genuine update on a specific application, set status to "other" and confidence below 0.5.
"""

DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"

# Free-tier RPM varies a lot by model (5 for plain Flash, 15 for Flash Lite,
# as of this writing) and has already changed under us once. Read at call
# time, not import time, so both the model and this interval can be swapped
# via env vars without a code edit if the quotas shift again later.
DEFAULT_MIN_SECONDS_BETWEEN_GEMINI_CALLS = 5.0
_last_gemini_call_at = 0.0

class ExtractedApplication(BaseModel):
    company: str
    role: str
    status: StatusType
    event_date: Optional[date] = None
    location: Optional[str] = None
    salary: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("company", "role", mode="before")
    @classmethod
    def _default_missing_identity_fields(cls, value):
        # A prompt instruction is a strong hint, not a guarantee against a
        # non-deterministic model — this is the safety net for the exact
        # failure that broke the pipeline when null slipped through anyway.
        return value if value else "Unknown"

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

def _throttle_gemini_calls() -> None:
    global _last_gemini_call_at
    min_seconds = float(os.environ.get("GEMINI_MIN_SECONDS_BETWEEN_CALLS", DEFAULT_MIN_SECONDS_BETWEEN_GEMINI_CALLS))
    elapsed = time.monotonic() - _last_gemini_call_at
    if elapsed < min_seconds:
        time.sleep(min_seconds - elapsed)
    _last_gemini_call_at = time.monotonic()

def _call_gemini(parsed_email: dict) -> dict:
    import google.generativeai as genai

    _throttle_gemini_calls()
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    model = genai.GenerativeModel(os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL))

    # A 429 here still gets a real, patient backoff rather than a fast retry
    # that just burns more of the same limited budget — scaled down from
    # earlier since Flash Lite's much higher RPM makes a 429 less likely and
    # less costly to wait out than it was on the old 5 RPM model.
    @retry_with_backoff(max_attempts=4, base_delay=5.0)
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
