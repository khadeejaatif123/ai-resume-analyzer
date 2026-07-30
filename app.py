import os
import io
import csv
import uuid
import json
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request, jsonify, render_template, abort, Response
from werkzeug.utils import secure_filename

import config
import database as db
import file_parser
import analyzer as ai_analyzer
import ranker

# ── App setup ──────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_LENGTH
os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)

# Background thread pool
_executor = ThreadPoolExecutor(max_workers=config.WORKER_THREADS)

# ── Helpers ────────────────────────────────────────────────────────────────────

def allowed_file(filename: str) -> bool:
    return "." in filename and \
           filename.rsplit(".", 1)[1].lower() in config.ALLOWED_EXTENSIONS


def file_type_from_name(filename: str) -> str:
    return filename.rsplit(".", 1)[1].lower()


def _process_candidate(candidate_id: str, file_path: str, file_type: str):
    """Background task: extract text → analyze → compute score → persist."""
    try:
        db.update_candidate_status(candidate_id, "processing")

        # 1. Extract text
        text, err = file_parser.extract_text(file_path, file_type)
        if err and not text:
            db.mark_failed(candidate_id)
            return

        # 2. Analyze with Claude
        try:
            analysis = ai_analyzer.analyze_resume(text)
        except Exception:
            db.mark_failed(candidate_id)
            return

        # 3. Pick primary role + compute experience score
        primary_role, primary_confidence = ranker.pick_primary_role(analysis.get("role_fit", []))
        exp_score = ranker.compute_experience_score(
            total_years=analysis.get("total_years_experience", 0),
            seniority_level=analysis.get("seniority_level", "junior"),
            role_fit_confidence=primary_confidence,
        )

        # 4. Persist
        db.update_candidate_analysis(
            candidate_id=candidate_id,
            analysis=analysis,
            experience_score=exp_score,
            primary_role=primary_role,
            primary_role_confidence=primary_confidence,
            raw_text=text,
        )
    except Exception:
        db.mark_failed(candidate_id)


def _save_upload(file) -> tuple[str, str, str]:
    """Save an uploaded FileStorage to disk. Returns (candidate_id, file_path, file_type)."""
    filename  = secure_filename(file.filename)
    file_type = file_type_from_name(filename)
    # Unique filename to avoid collisions
    unique_name = f"{uuid.uuid4().hex}_{filename}"
    file_path   = os.path.join(config.UPLOAD_FOLDER, unique_name)
    file.save(file_path)
    return unique_name, file_path, file_type


# ── UI Routes ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    taxonomy = db.get_role_taxonomy()
    return render_template("index.html", taxonomy=taxonomy)


@app.route("/candidate/<candidate_id>")
def candidate_detail(candidate_id):
    candidate = db.get_candidate(candidate_id)
    if not candidate:
        abort(404)
    analysis = candidate.get("analysis_json") or {}
    return render_template("candidate.html", candidate=candidate, analysis=analysis)


# ── API: Upload ────────────────────────────────────────────────────────────────

@app.route("/api/resumes", methods=["POST"])
def upload_single():
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "Empty filename"}), 400
    if not allowed_file(file.filename):
        return jsonify({"error": "File type not allowed. Use PDF, DOCX, or TXT."}), 400

    _, file_path, file_type = _save_upload(file)
    record = db.create_candidate(
        original_filename=file.filename,
        file_type=file_type,
        resume_file_path=file_path,
    )
    _executor.submit(_process_candidate, record["candidate_id"], file_path, file_type)
    return jsonify(record), 202


@app.route("/api/resumes/batch", methods=["POST"])
def upload_batch():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No files provided"}), 400

    results = []
    for file in files:
        if not file.filename or not allowed_file(file.filename):
            results.append({"filename": file.filename, "error": "Skipped (invalid type)"})
            continue
        _, file_path, file_type = _save_upload(file)
        record = db.create_candidate(
            original_filename=file.filename,
            file_type=file_type,
            resume_file_path=file_path,
        )
        _executor.submit(_process_candidate, record["candidate_id"], file_path, file_type)
        results.append({**record, "filename": file.filename})

    return jsonify(results), 202


# ── API: Read ──────────────────────────────────────────────────────────────────

@app.route("/api/resumes/<candidate_id>", methods=["GET"])
def get_resume(candidate_id):
    candidate = db.get_candidate(candidate_id)
    if not candidate:
        return jsonify({"error": "Not found"}), 404
    return jsonify(candidate)


@app.route("/api/roles", methods=["GET"])
def get_roles():
    return jsonify(db.get_role_taxonomy())


@app.route("/api/roles/<role_key>/candidates", methods=["GET"])
def get_role_candidates(role_key):
    candidates = db.get_candidates_for_role(role_key)
    ranked = ranker.rank_candidates(candidates)
    return jsonify(ranked)


@app.route("/api/candidates", methods=["GET"])
def get_all_candidates_api():
    status_filter = request.args.get("status")
    all_c = db.get_all_candidates()
    if status_filter:
        all_c = [c for c in all_c if c.get("analysis_status") == status_filter]
    return jsonify(all_c)


# ── API: Export ────────────────────────────────────────────────────────────────

@app.route("/api/roles/<role_key>/export.csv", methods=["GET"])
def export_role_csv(role_key):
    candidates = db.get_candidates_for_role(role_key)
    ranked = ranker.rank_candidates(candidates)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Rank", "Candidate Name", "Experience Score", "Overall Score",
        "Seniority", "Years Experience", "Primary Role", "Role Confidence",
        "Queue Position", "Uploaded At", "FCFS Tie", "Filename",
    ])
    for c in ranked:
        writer.writerow([
            c.get("rank"),
            c.get("candidate_name") or "Unknown",
            c.get("experience_score"),
            c.get("overall_score"),
            c.get("seniority_level"),
            c.get("total_years_experience"),
            c.get("primary_role"),
            c.get("primary_role_confidence"),
            c.get("queue_position"),
            c.get("uploaded_at"),
            "Yes" if c.get("fcfs_tie") else "No",
            c.get("original_filename"),
        ])

    output.seek(0)
    display_name = role_key.replace("_", "-")
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=shortlist-{display_name}.csv"},
    )


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    db.init_db()
    print("=" * 60)
    print("  AI Resume Screening System")
    print("  http://127.0.0.1:5000")
    print("=" * 60)
    app.run(debug=True, use_reloader=False)
