"""
Provenance Guard — Flask API

Endpoints:
  POST /submit              Submit content for attribution analysis
  POST /appeal              Contest a classification
  GET  /status/<content_id> Get current status of a submission
  GET  /log                 View the structured audit log
"""

import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import database
from detection import llm_signal, stylometric, scorer

load_dotenv()

app = Flask(__name__)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

database.init_db()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _error(message: str, code: int):
    return jsonify({"error": message}), code


# ---------------------------------------------------------------------------
# POST /submit
# Rate limit: 10 requests per minute per IP
# ---------------------------------------------------------------------------

@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute")
def submit():
    """
    Accept a piece of text for attribution analysis.

    Request body (JSON):
      {
        "text":       string (required),
        "creator_id": string (optional)
      }

    Returns:
      {
        "content_id":    string,
        "result":        "ai" | "human" | "uncertain",
        "ai_probability": float,
        "confidence":    float,
        "label_text":    string,
        "label_variant": string,
        "signals": {
          "llm": { "score", "rationale", "key_indicators", "model" },
          "stylometric": { "score", "sub_scores", "word_count" }
        },
        "timestamp": string
      }
    """
    body = request.get_json(silent=True)
    if not body:
        return _error("Request body must be valid JSON.", 400)

    text = body.get("text", "").strip()
    if not text:
        return _error("'text' field is required and must not be empty.", 400)
    if len(text) < 20:
        return _error("Text must be at least 20 characters for analysis.", 400)
    if len(text) > 50_000:
        return _error("Text exceeds maximum length of 50,000 characters.", 413)

    creator_id = body.get("creator_id") or None
    content_id = str(uuid.uuid4())

    # --- Run detection pipeline ---
    llm_result = llm_signal.analyze(text)
    style_result = stylometric.analyze(text)

    # --- Combine scores (pass word_count so weights adapt to text length) ---
    score_result = scorer.combine_scores(
        llm_result["score"],
        style_result["score"],
        word_count=style_result.get("word_count", 999),
    )

    # --- Generate transparency label ---
    label_result = scorer.build_label(
        score_result["ai_probability"], score_result["confidence"]
    )

    # --- Write to audit log ---
    database.log_submission(
        content_id=content_id,
        creator_id=creator_id,
        text=text,
        llm_result=llm_result,
        style_result=style_result,
        score_result=score_result,
        label_result=label_result,
    )

    return jsonify({
        "content_id": content_id,
        "result": label_result["result"],
        "ai_probability": score_result["ai_probability"],
        "confidence": score_result["confidence"],
        "label_text": label_result["label_text"],
        "label_variant": label_result["variant"],
        "signals": {
            "llm": {
                "score": llm_result["score"],
                "rationale": llm_result.get("rationale", ""),
                "key_indicators": llm_result.get("key_indicators", []),
                "model": llm_result.get("model", ""),
            },
            "stylometric": {
                "score": style_result["score"],
                "sub_scores": style_result.get("sub_scores", {}),
                "word_count": style_result.get("word_count", 0),
            },
            "weights_used": score_result.get("weights_used", {}),
        },
        "timestamp": _now_iso(),
    }), 200


# ---------------------------------------------------------------------------
# POST /appeal
# Rate limit: 5 requests per minute per IP
# ---------------------------------------------------------------------------

@app.route("/appeal", methods=["POST"])
@limiter.limit("5 per minute")
def appeal():
    """
    Contest an attribution classification.

    Request body (JSON):
      {
        "content_id": string (required),
        "creator_id": string (optional),
        "reason":     string (required — creator's explanation)
      }

    Returns:
      {
        "appeal_id":  string,
        "content_id": string,
        "status":     "under_review",
        "message":    string,
        "timestamp":  string
      }
    """
    body = request.get_json(silent=True)
    if not body:
        return _error("Request body must be valid JSON.", 400)

    content_id = body.get("content_id", "").strip()
    if not content_id:
        return _error("'content_id' is required.", 400)

    reason = body.get("reason", "").strip()
    if not reason:
        return _error("'reason' is required — please explain why you believe the classification is incorrect.", 400)
    if len(reason) < 10:
        return _error("'reason' must be at least 10 characters.", 400)

    creator_id = body.get("creator_id") or None

    # Verify the submission exists
    submission = database.get_submission(content_id)
    if submission is None:
        return _error(f"No submission found with content_id '{content_id}'.", 404)

    # Check if already under review
    if submission["status"] == "under_review":
        return _error("This content already has an appeal under review.", 409)

    appeal_id = str(uuid.uuid4())

    database.log_appeal(
        appeal_id=appeal_id,
        content_id=content_id,
        creator_id=creator_id,
        reason=reason,
        original_result=submission["result"],
        original_ai_prob=submission["ai_probability"],
    )

    return jsonify({
        "appeal_id": appeal_id,
        "content_id": content_id,
        "status": "under_review",
        "message": (
            "Your appeal has been logged. The classification for this content has been "
            "updated to 'under review'. Our moderation team will review your case alongside "
            "the original detection data."
        ),
        "original_result": submission["result"],
        "original_ai_probability": submission["ai_probability"],
        "timestamp": _now_iso(),
    }), 202


# ---------------------------------------------------------------------------
# GET /status/<content_id>
# ---------------------------------------------------------------------------

@app.route("/status/<content_id>", methods=["GET"])
def status(content_id: str):
    """Return current status of a submission, including any appeal."""
    submission = database.get_submission(content_id)
    if submission is None:
        return _error(f"No submission found with content_id '{content_id}'.", 404)

    appeal = database.get_appeal_for_submission(content_id)

    return jsonify({
        "content_id": content_id,
        "result": submission["result"],
        "status": submission["status"],
        "ai_probability": submission["ai_probability"],
        "confidence": submission["confidence"],
        "label_variant": submission["label_variant"],
        "label_text": submission["label_text"],
        "creator_id": submission["creator_id"],
        "created_at": submission["created_at"],
        "updated_at": submission["updated_at"],
        "appeal": appeal,
    }), 200


# ---------------------------------------------------------------------------
# GET /log
# ---------------------------------------------------------------------------

@app.route("/log", methods=["GET"])
def log():
    """
    Return paginated audit log entries.

    Query params:
      limit  (int, default 20, max 100)
      offset (int, default 0)
    """
    try:
        limit = min(int(request.args.get("limit", 20)), 100)
        offset = int(request.args.get("offset", 0))
    except ValueError:
        return _error("'limit' and 'offset' must be integers.", 400)

    return jsonify(database.get_log(limit=limit, offset=offset)), 200


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(429)
def rate_limit_exceeded(e):
    return jsonify({
        "error": "Rate limit exceeded. Please slow down your requests.",
        "retry_after": str(e.description),
    }), 429


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Endpoint not found."}), 404


@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({"error": "Method not allowed."}), 405


if __name__ == "__main__":
    app.run(debug=True, port=5000)
