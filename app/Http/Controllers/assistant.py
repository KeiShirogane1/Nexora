from flask import Blueprint, jsonify, request, session

from app.Http.Middleware.security import login_required
from app.Services.ai_assistant_service import (
    AIServiceError,
    answer_role_question,
    explain_ml_evidence,
)

assistant_bp = Blueprint("assistant", __name__)


@assistant_bp.route("/assistant/ask", methods=["POST"])
@login_required
def ask():
    data = request.get_json(silent=True) or {}
    question = data.get("question")

    try:
        result = answer_role_question(session.get("user_id"), question)
    except PermissionError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except AIServiceError:
        return jsonify(
            {
                "ok": False,
                "error": "Nexora AI is temporarily unavailable. Please try again later.",
            }
        ), 502

    return jsonify({"ok": True, **result})


@assistant_bp.route("/assistant/ml-explanation", methods=["POST"])
@login_required
def ml_explanation():
    data = request.get_json(silent=True) or {}
    evidence = data.get("evidence")

    try:
        result = explain_ml_evidence(session.get("user_id"), evidence)
    except PermissionError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except AIServiceError:
        return jsonify(
            {
                "ok": False,
                "error": "Nexora AI is temporarily unavailable. Please try again later.",
            }
        ), 502

    return jsonify({"ok": True, **result})
