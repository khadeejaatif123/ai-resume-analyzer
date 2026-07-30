import os
from dotenv import load_dotenv

load_dotenv()

# ── Anthropic API ──────────────────────────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.3-70b-versatile"

# ── File storage ───────────────────────────────────────────────────────────────
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
ALLOWED_EXTENSIONS = {"pdf", "docx", "txt"}
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB per file

# ── Database ───────────────────────────────────────────────────────────────────
DATABASE_PATH = os.path.join(os.path.dirname(__file__), "resume_screening.db")

# ── Experience score weights (must sum to 1.0) ─────────────────────────────────
WEIGHT_YEARS      = 0.50
WEIGHT_SENIORITY  = 0.35
WEIGHT_FIT        = 0.15

# ── Seniority → numeric mapping ────────────────────────────────────────────────
SENIORITY_NUMERIC = {
    "intern":     0,
    "junior":     1,
    "mid":        2,
    "senior":     3,
    "lead":       4,
    "principal":  5,
    "executive":  6,
}

# ── FCFS tie-break epsilon ─────────────────────────────────────────────────────
TIE_EPSILON = 1.0   # scores within ±1 point are considered a tie

# ── Minimum confidence to assign a role (otherwise → Unclassified) ─────────────
MIN_ROLE_CONFIDENCE = 40

# ── Role taxonomy ─────────────────────────────────────────────────────────────
# Edit this list to add/remove roles without touching any other code.
ROLE_TAXONOMY = [
    {"role_key": "frontend_engineering",  "display_name": "Software Engineering — Frontend"},
    {"role_key": "backend_engineering",   "display_name": "Software Engineering — Backend"},
    {"role_key": "fullstack_engineering", "display_name": "Software Engineering — Full Stack"},
    {"role_key": "data_analytics",        "display_name": "Data / Analytics"},
    {"role_key": "product_management",    "display_name": "Product Management"},
    {"role_key": "design",                "display_name": "Design (UX/UI/Product Design)"},
    {"role_key": "sales",                 "display_name": "Sales"},
    {"role_key": "marketing",             "display_name": "Marketing"},
    {"role_key": "customer_support",      "display_name": "Customer Support / Success"},
    {"role_key": "operations",            "display_name": "Operations"},
    {"role_key": "finance_accounting",    "display_name": "Finance / Accounting"},
    {"role_key": "hr_recruiting",         "display_name": "Human Resources / Recruiting"},
    {"role_key": "unclassified",          "display_name": "Other / Unclassified"},
]

ROLE_KEY_TO_DISPLAY = {r["role_key"]: r["display_name"] for r in ROLE_TAXONOMY}
ROLE_DISPLAY_TO_KEY = {r["display_name"]: r["role_key"] for r in ROLE_TAXONOMY}

# Background worker thread pool size
WORKER_THREADS = 4
