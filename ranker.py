from config import (
    WEIGHT_YEARS, WEIGHT_SENIORITY, WEIGHT_FIT,
    SENIORITY_NUMERIC, TIE_EPSILON, MIN_ROLE_CONFIDENCE,
)


def compute_experience_score(
    total_years: float,
    seniority_level: str,
    role_fit_confidence: float,
) -> float:
    """
    experience_score =
        (total_years_experience  * WEIGHT_YEARS)
      + (seniority_level_numeric * WEIGHT_SENIORITY)
      + (role_fit_confidence     * WEIGHT_FIT)

    Seniority numeric: intern=0 … executive=6
    role_fit_confidence is 0-100; we scale it to 0-10 for parity with typical years ranges.
    """
    seniority_num = SENIORITY_NUMERIC.get(str(seniority_level).lower(), 1)
    # Normalise confidence to a 0-10 scale so weights stay intuitive
    fit_scaled = (role_fit_confidence / 100.0) * 10.0

    score = (
        (total_years    * WEIGHT_YEARS)
      + (seniority_num  * WEIGHT_SENIORITY)
      + (fit_scaled     * WEIGHT_FIT)
    )
    return round(score, 4)


def pick_primary_role(role_fit_list: list[dict], min_confidence: int = MIN_ROLE_CONFIDENCE) -> tuple[str, float]:
    """
    Return (primary_role_display_name, confidence).
    The first (highest-confidence) role that meets the threshold wins.
    Falls back to 'Other / Unclassified' if none qualifies.
    """
    for rf in role_fit_list:
        if rf.get("confidence", 0) >= min_confidence:
            return rf["role"], float(rf["confidence"])
    return "Other / Unclassified", 100.0


def is_fcfs_tie(score_a: float, score_b: float) -> bool:
    """Return True when two scores are within TIE_EPSILON of each other."""
    return abs(score_a - score_b) <= TIE_EPSILON


def rank_candidates(candidates: list[dict]) -> list[dict]:
    """
    Sort a list of candidate dicts using the deterministic 3-key comparator:
        1. experience_score  DESC
        2. uploaded_at       ASC   (tie-break — FCFS)
        3. candidate_id      ASC   (final fallback)

    Also annotates each dict with:
        rank          (1-indexed)
        fcfs_tie      (True if this candidate's score is within epsilon of
                       the immediately-preceding candidate's score)
    """
    sorted_candidates = sorted(
        candidates,
        key=lambda c: (
            -(c.get("experience_score") or 0),   # DESC
             c.get("uploaded_at", ""),             # ASC
             c.get("candidate_id", ""),            # ASC
        ),
    )

    prev_score = None
    for i, c in enumerate(sorted_candidates):
        c["rank"] = i + 1
        score = c.get("experience_score") or 0
        if prev_score is not None and is_fcfs_tie(score, prev_score):
            c["fcfs_tie"] = True
        else:
            c["fcfs_tie"] = False
        prev_score = score

    return sorted_candidates
