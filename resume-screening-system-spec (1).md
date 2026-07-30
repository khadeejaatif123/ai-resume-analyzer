# Resume Screening & Ranking System — Build Spec

## 1. Overview

A system that ingests a **batch of resumes**, analyzes each one, sorts candidates
into the job **role** they're the best fit for, **ranks** candidates within each
role by experience level, and preserves **upload order** so ties can be broken
first-come-first-served (FCFS).

This extends a single-resume analyzer (score + feedback) into a multi-candidate
**screening and shortlisting tool** for someone reviewing many applicants at once.

---

## 2. Goals

- [ ] Accept multiple resumes in one batch (or streamed in one at a time over time).
- [ ] Extract structured data from each resume (skills, years of experience, past titles, education).
- [ ] Classify each candidate into one (or more) suitable **role buckets**.
- [ ] Rank candidates **within each role bucket** from most to least experienced.
- [ ] Record the **exact upload timestamp** of every resume.
- [ ] When two candidates tie on rank/experience, break the tie by **upload time (earlier wins)**.
- [ ] Present results as a browsable, filterable, exportable dashboard.

### Non-goals (for v1)
- Not making hiring decisions — this is a triage/shortlist tool, not an ATS replacement.
- Not doing interview scheduling or communication with candidates.
- Not doing duplicate-person detection across different resume files (nice-to-have later).

---

## 3. User Flow

1. **Upload** — Recruiter uploads one or many resumes (drag-and-drop multiple files, or an API endpoint that accepts one file per request over time — e.g. from an intake form).
2. **Ingest** — Each file is timestamped at the moment it's received and queued for analysis.
3. **Analyze** — Each resume is parsed and sent to Claude for structured extraction + scoring (reuse the existing single-resume analyzer logic).
4. **Classify** — The system assigns the candidate to the role bucket(s) their experience best matches.
5. **Rank** — Within each role bucket, candidates are sorted by a computed experience score, highest first. Ties are broken by earliest upload timestamp.
6. **Review** — Recruiter opens a dashboard, picks a role tab, and sees a ranked list. Each row shows rank, name, experience score, upload timestamp/queue position, and a link to the full analysis.
7. **Export** (optional) — Download the ranked shortlist per role as CSV.

---

## 4. Core Features

### 4.1 Bulk Resume Ingestion
- Accept `PDF`, `DOCX`, `TXT`.
- Support multi-file upload in one request AND single-file upload over time (both must timestamp correctly).
- Store the raw file, extracted text, and an `uploaded_at` timestamp (server time, UTC, ISO 8601, millisecond precision) the moment the file is received — **not** when analysis finishes. This is what FCFS is based on.
- Give every submission a unique `candidate_id` and monotonically increasing `queue_position` (assigned in upload order, not analysis-completion order, since analysis may run in parallel/out of order).

### 4.2 Resume Analysis (per candidate)
Reuse/extend the existing single-resume analyzer. For this system, the model call should additionally extract **structured fields**, not just narrative feedback:

```json
{
  "candidate_name": "string | null",
  "total_years_experience": "number",
  "seniority_level": "intern | junior | mid | senior | lead | principal | executive",
  "primary_skills": ["string", ...],
  "past_titles": ["string", ...],
  "education_level": "string",
  "role_fit": [
    { "role": "string (from role taxonomy)", "confidence": "0-100", "reasoning": "string" }
  ],
  "overall_score": "0-100",
  "summary": "string",
  "strengths": ["string", ...],
  "weaknesses": ["string", ...]
}
```

`role_fit` is a ranked list — a candidate can fit more than one role bucket (e.g. "Backend Engineer" and "Data Engineer"), but the system assigns them primarily to their **top-confidence role** for ranking purposes, while still being visible/filterable under secondary roles.

### 4.3 Role Classification

Default role taxonomy (should be configurable, not hardcoded forever):

- Software Engineering — Frontend
- Software Engineering — Backend
- Software Engineering — Full Stack
- Data / Analytics (Data Science, Data Engineering, Analytics)
- Product Management
- Design (UX/UI/Product Design)
- Sales
- Marketing
- Customer Support / Success
- Operations
- Finance / Accounting
- Human Resources / Recruiting
- Other / Unclassified

Requirements:
- Classification is **model-driven** (send the resume text + role taxonomy list to Claude, ask it to pick best-fit role(s) with confidence scores) — not keyword regex matching, since titles vary wildly.
- If no role clears a minimum confidence threshold (e.g. 40%), bucket the candidate under **"Other / Unclassified"** for manual review rather than forcing a bad fit.
- Role taxonomy should live in a config file/table so it can be edited without code changes (a recruiter may want to add "DevOps" or "Legal" as needed).

### 4.4 Experience Ranking (within a role bucket)

Compute a single **experience score** per candidate to sort by. Suggested formula (tune as needed):

```
experience_score =
    (total_years_experience * weight_years)
  + (seniority_level_numeric * weight_seniority)
  + (role_fit_confidence * weight_fit)
```

Where:
- `seniority_level_numeric`: intern=0, junior=1, mid=2, senior=3, lead=4, principal=5, executive=6
- Default weights: `weight_years=0.5`, `weight_seniority=0.35`, `weight_fit=0.15` (make these configurable constants).

Sort candidates within a role bucket by `experience_score` descending.

### 4.5 First-Come-First-Served Tie-Breaking

- If two or more candidates have an **identical (or within-epsilon, e.g. ±1 point) experience_score** in the same role bucket, the candidate with the **earlier `uploaded_at` timestamp** ranks higher.
- This must be deterministic — document the exact comparator:
  ```
  sort by:
    1. experience_score DESC
    2. uploaded_at ASC   (tie-break)
    3. candidate_id ASC  (final fallback, guarantees stable order)
  ```
- Surface the FCFS tie-break visibly in the UI (e.g. a small "queued Xth" badge) so it's transparent why two similarly-scored candidates are ordered the way they are.

---

## 5. Data Model

### `candidates` table
| field | type | notes |
|---|---|---|
| candidate_id | UUID | primary key |
| original_filename | string | |
| file_type | enum(pdf, docx, txt) | |
| uploaded_at | timestamp (UTC, ms precision) | set at ingestion, immutable |
| queue_position | integer | monotonic counter at ingestion time |
| analysis_status | enum(queued, processing, complete, failed) | |
| candidate_name | string, nullable | extracted |
| total_years_experience | number, nullable | extracted |
| seniority_level | enum, nullable | extracted |
| overall_score | integer 0-100, nullable | extracted |
| experience_score | number, nullable | computed |
| primary_role | string, nullable | top role_fit entry |
| primary_role_confidence | number, nullable | |
| raw_extracted_text | text | for re-analysis / debugging |
| analysis_json | JSON | full structured analyzer output |
| resume_file_path | string | storage location |

### `role_fits` table (many-to-many: a candidate can fit multiple roles)
| field | type | notes |
|---|---|---|
| id | UUID | |
| candidate_id | UUID | FK |
| role | string | from role taxonomy |
| confidence | number 0-100 | |
| reasoning | text | |

### `role_taxonomy` table (configurable)
| field | type | notes |
|---|---|---|
| role_key | string | e.g. `backend_engineering` |
| display_name | string | e.g. "Software Engineering — Backend" |
| active | boolean | |

---

## 6. API Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/resumes` | Upload one resume; returns `candidate_id` + `uploaded_at` immediately, analysis runs async |
| `POST` | `/api/resumes/batch` | Upload multiple resumes at once |
| `GET` | `/api/resumes/:id` | Full analysis for one candidate |
| `GET` | `/api/roles` | List role taxonomy |
| `GET` | `/api/roles/:role_key/candidates` | Ranked candidate list for a role (already sorted per §4.4/§4.5) |
| `GET` | `/api/candidates?status=queued` | Check processing queue status |
| `GET` | `/api/roles/:role_key/export.csv` | Export ranked shortlist as CSV |

Async processing note: since analysis is an LLM call, uploads should return immediately (`202 Accepted` + `candidate_id`) and analysis should run in a background worker/queue, updating `analysis_status`. The frontend should poll or use websockets to reflect status changes without blocking new uploads.

---

## 7. Ranking/Classification Prompt Design Notes

- Send the role taxonomy list explicitly in the prompt so the model chooses from a **closed set**, not free text — this keeps role buckets consistent across candidates.
- Ask for `total_years_experience` as a number computed from the resume's work history dates, not a self-reported number from the resume (people rarely state it explicitly).
- Force strict JSON output (same pattern as the single-resume analyzer: system prompt says "JSON only," code strips accidental fences, `json.loads` wrapped in try/except with a retry-or-fail path).

---

## 8. UI Requirements

- **Role tabs/sidebar**: one tab per active role in the taxonomy, plus "All" and "Unclassified."
- **Ranked list view** per role: rank number, candidate name, experience_score, seniority level, years of experience, upload timestamp, queue position, "view full analysis" link.
- **Tie indicator**: visually flag when a candidate's rank was decided by FCFS tie-break rather than a clear score difference.
- **Upload panel**: supports multi-file drag-and-drop; shows live status (queued → processing → complete) per file.
- **Candidate detail view**: reuse the existing single-resume "redline" analysis view (score stamp, strengths/weaknesses, suggestions) plus the new role-fit breakdown.
- **Export button** per role tab → CSV.

---

## 9. Tech Stack Recommendation

(Consistent with the existing single-resume analyzer — Python/Flask backend, Claude API for analysis.)

- **Backend**: Flask (or FastAPI if you want native async + background tasks more cleanly)
- **Background jobs**: Celery + Redis, or simple `ThreadPoolExecutor` for lower volume
- **DB**: PostgreSQL (or SQLite for a local/prototype build) — needed for the multi-table relational model above
- **File storage**: local disk for prototype; S3-compatible bucket for production
- **Frontend**: same server-rendered Flask/Jinja + vanilla JS pattern as the single-resume tool, extended with tabs and a table/list view — or upgrade to a small React app if the dashboard grows complex
- **Model**: Claude Sonnet 5 (`claude-sonnet-5`) via the Anthropic API for both extraction/classification and scoring — one call per resume can return everything in §4.2's JSON shape

---

## 10. Edge Cases to Handle

- Resume with no extractable work history (e.g. new grad) — should still classify and get a low-but-valid experience_score, not error out.
- Resume that fits no role above the confidence threshold — bucket as "Other / Unclassified," don't force it.
- Duplicate upload of the exact same file — allow it (recruiter may re-upload); each gets its own `candidate_id` and timestamp.
- Corrupted/unparseable file — mark `analysis_status = failed`, surface a clear error in the UI, don't block the rest of the batch.
- Batch upload where files finish analysis out of order (async) — ranking must always be computed from `uploaded_at`/`queue_position`, never from completion order.
- Very large batch (100+ resumes) — queue should process without timing out the upload request itself (hence async processing, not synchronous analysis on upload).

---

## 11. Acceptance Criteria

- [ ] Uploading a batch of resumes assigns each an immutable `uploaded_at` timestamp and `queue_position` at receipt time, before analysis starts.
- [ ] Each resume is classified into at least one role from the taxonomy, or "Unclassified" if none qualifies.
- [ ] Within any role's candidate list, sorting strictly follows: experience_score DESC → uploaded_at ASC → candidate_id ASC.
- [ ] Re-running the ranking query on the same data always produces the same order (deterministic).
- [ ] Two resumes with genuinely identical qualifications are ordered by whichever was uploaded first.
- [ ] The dashboard can filter to a single role and show a clean ranked list with visible rank, score, and timestamp.
- [ ] CSV export from a role tab matches exactly what's shown on screen, in the same order.

---

## 12. Suggested Build Order

1. Data model + migrations (candidates, role_fits, role_taxonomy tables).
2. Single-file ingestion endpoint with correct timestamping (reuse existing text-extraction utility).
3. Analyzer prompt update to return the full structured JSON in §4.2.
4. Background job runner for async analysis.
5. Ranking query (§4.4 + §4.5 comparator) as a reusable, unit-tested function — this is the part most worth getting exactly right and covering with tests for the tie-break case specifically.
6. Role-bucketed API endpoints.
7. Dashboard UI: tabs, ranked list, candidate detail, upload panel with live status.
8. Batch upload + CSV export.
