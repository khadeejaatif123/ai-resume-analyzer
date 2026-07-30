import json
import re
from groq import Groq
from config import (
    GROQ_API_KEY, GROQ_MODEL,
    ROLE_TAXONOMY, MIN_ROLE_CONFIDENCE
)

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = Groq(api_key=GROQ_API_KEY)
    return _client


SYSTEM_PROMPT = """You are an expert resume analyzer and HR consultant.
Your ONLY output must be a valid JSON object — no markdown, no code fences, no prose.
Analyze the provided resume text and return structured data exactly matching the schema below."""


def _build_user_prompt(resume_text: str) -> str:
    role_list = "\n".join(f'  - "{r["display_name"]}"' for r in ROLE_TAXONOMY)
    return f"""Analyze this resume and return a single JSON object with EXACTLY these fields:

{{
  "candidate_name": "string or null — the person's full name",
  "total_years_experience": <number — compute from work history dates, not self-reported>,
  "seniority_level": "<one of: intern | junior | mid | senior | lead | principal | executive>",
  "primary_skills": ["list of technical/professional skills"],
  "past_titles": ["list of job titles held"],
  "education_level": "string — highest education (e.g. 'Bachelor of Computer Science')",
  "role_fit": [
    {{
      "role": "<MUST be one of the roles listed below>",
      "confidence": <integer 0-100>,
      "reasoning": "brief explanation"
    }}
  ],
  "overall_score": <integer 0-100 — holistic candidate quality>,
  "summary": "2-3 sentence summary of the candidate",
  "strengths": ["list of key strengths"],
  "weaknesses": ["list of areas for improvement"]
}}

AVAILABLE ROLES (use EXACT strings, no variations):
{role_list}

Rules:
- role_fit must be sorted by confidence descending
- Only include roles where confidence >= 20
- If no role reaches {MIN_ROLE_CONFIDENCE}, include "Other / Unclassified" with confidence=100
- total_years_experience: estimate from employment dates (e.g. 2019-2023 = 4 years); if no dates, estimate from context
- Return ONLY valid JSON, nothing else

RESUME TEXT:
{resume_text}"""


def analyze_resume(resume_text: str, max_retries: int = 2) -> dict:
    """
    Call Groq to analyze a resume. Returns the parsed JSON dict.
    Raises ValueError if parsing fails after retries.
    """
    client = _get_client()
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": _build_user_prompt(resume_text)},
                ],
                temperature=0.1,
                max_tokens=2048,
            )
            raw = response.choices[0].message.content.strip()

            # Strip accidental markdown fences
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            raw = raw.strip()

            data = json.loads(raw)
            return _validate_and_normalise(data)

        except json.JSONDecodeError as e:
            last_error = f"JSON parse error (attempt {attempt+1}): {e}"
        except Exception as e:
            last_error = f"API error (attempt {attempt+1}): {e}"
            if attempt == max_retries:
                raise

    raise ValueError(f"Analysis failed after {max_retries+1} attempts. Last error: {last_error}")


def _validate_and_normalise(data: dict) -> dict:
    """Ensure required fields have sane defaults."""
    VALID_SENIORITY = {"intern", "junior", "mid", "senior", "lead", "principal", "executive"}
    VALID_ROLES     = {r["display_name"] for r in ROLE_TAXONOMY}

    data.setdefault("candidate_name", None)
    data.setdefault("total_years_experience", 0)
    data.setdefault("seniority_level", "junior")
    data.setdefault("primary_skills", [])
    data.setdefault("past_titles", [])
    data.setdefault("education_level", "")
    data.setdefault("role_fit", [])
    data.setdefault("overall_score", 0)
    data.setdefault("summary", "")
    data.setdefault("strengths", [])
    data.setdefault("weaknesses", [])

    # Normalise seniority
    sl = str(data["seniority_level"]).lower().strip()
    data["seniority_level"] = sl if sl in VALID_SENIORITY else "junior"

    # Clamp overall_score
    data["overall_score"] = max(0, min(100, int(data.get("overall_score", 0))))

    # Normalise total_years_experience
    try:
        data["total_years_experience"] = float(data["total_years_experience"])
    except (TypeError, ValueError):
        data["total_years_experience"] = 0.0

    # Normalise role_fit
    cleaned = []
    for rf in data.get("role_fit", []):
        role = rf.get("role", "").strip()
        conf = int(rf.get("confidence", 0))
        if role in VALID_ROLES:
            cleaned.append({
                "role":       role,
                "confidence": max(0, min(100, conf)),
                "reasoning":  rf.get("reasoning", ""),
            })
    # Sort by confidence desc
    cleaned.sort(key=lambda x: x["confidence"], reverse=True)

    # If nothing survived, bucket as Unclassified
    if not cleaned:
        cleaned = [{"role": "Other / Unclassified", "confidence": 100, "reasoning": "No role met the confidence threshold."}]

    data["role_fit"] = cleaned
    return data
