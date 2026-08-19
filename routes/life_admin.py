"""routes/life_admin.py — Career, decisions, finance, legal, reading, social, tutor, planning routes, split out of the former
monolithic server.py. Registered onto the main Flask app in server.py
via app.register_blueprint(life_admin_bp); nothing here changes behavior,
only where the code lives.
"""
from flask import Blueprint, request, jsonify

from core.app_state import (
    career,
    decisions,
    finance,
    hierarchical,
    legal,
    reading_mem,
    social,
    tutor,
)

life_admin_bp = Blueprint("life_admin", __name__)


@life_admin_bp.route("/friday/career/resume", methods=["POST"])
def career_resume():
    data = request.get_json(silent=True) or {}
    if not career:
        return jsonify({"error": "unavailable"}), 503
    return jsonify(career.optimize_resume(data.get("resume", ""), data.get("job_description", "")))


@life_admin_bp.route("/friday/career/cover-letter", methods=["POST"])
def career_cover_letter():
    data = request.get_json(silent=True) or {}
    if not career:
        return jsonify({"error": "unavailable"}), 503
    return jsonify({"cover_letter": career.cover_letter(
        data.get("resume", ""), data.get("job_description", ""), data.get("company", ""))})


@life_admin_bp.route("/friday/career/interview-prep", methods=["POST"])
def career_interview_prep():
    data = request.get_json(silent=True) or {}
    if not career:
        return jsonify({"error": "unavailable"}), 503
    return jsonify(career.interview_prep(data.get("job_description", ""), data.get("company", "")))


@life_admin_bp.route("/friday/career/salary", methods=["POST"])
def career_salary():
    data = request.get_json(silent=True) or {}
    if not career:
        return jsonify({"error": "unavailable"}), 503
    return jsonify(career.salary_research(data.get("role", ""), data.get("location", "")))


@life_admin_bp.route("/friday/decisions/analyze", methods=["POST"])
def decisions_analyze():
    data = request.get_json(silent=True) or {}
    if not decisions:
        return jsonify({"error": "unavailable"}), 503
    return jsonify(decisions.analyze(data.get("decision", ""), data.get("options")))


@life_admin_bp.route("/friday/decisions/pros-cons", methods=["POST"])
def decisions_pros_cons():
    data = request.get_json(silent=True) or {}
    if not decisions:
        return jsonify({"error": "unavailable"}), 503
    return jsonify(decisions.pros_cons(data.get("topic", "")))


@life_admin_bp.route("/friday/decisions/devil-advocate", methods=["POST"])
def decisions_devil_advocate():
    data = request.get_json(silent=True) or {}
    if not decisions:
        return jsonify({"error": "unavailable"}), 503
    return jsonify({"response": decisions.devil_advocate(
        data.get("decision", ""), data.get("chosen_option", ""))})


@life_admin_bp.route("/friday/decisions/risk", methods=["POST"])
def decisions_risk():
    data = request.get_json(silent=True) or {}
    if not decisions:
        return jsonify({"error": "unavailable"}), 503
    return jsonify(decisions.risk_analysis(data.get("plan", "")))


@life_admin_bp.route("/friday/decisions/swot", methods=["POST"])
def decisions_swot():
    data = request.get_json(silent=True) or {}
    if not decisions:
        return jsonify({"error": "unavailable"}), 503
    return jsonify(decisions.swot(data.get("subject", "")))


@life_admin_bp.route("/friday/decisions/log", methods=["POST"])
def decisions_log_decision():
    data = request.get_json(silent=True) or {}
    if not decisions:
        return jsonify({"error": "unavailable"}), 503
    return jsonify(decisions.log_decision(
        data.get("decision", ""), data.get("chosen_option", ""), data.get("notes", "")))


@life_admin_bp.route("/friday/decisions/outcome", methods=["POST"])
def decisions_record_outcome():
    data = request.get_json(silent=True) or {}
    if not decisions:
        return jsonify({"error": "unavailable"}), 503
    decision_id = data.get("decision_id")
    if decision_id is None:
        return jsonify({"error": "decision_id required"}), 400
    return jsonify(decisions.record_outcome(decision_id, data.get("outcome", "")))


@life_admin_bp.route("/friday/decisions/history")
def decisions_history():
    if not decisions:
        return jsonify({"decisions": []})
    return jsonify({"decisions": decisions.decision_log()})


@life_admin_bp.route("/friday/decisions/followups")
def decisions_followups():
    if not decisions:
        return jsonify({"followups": []})
    days = request.args.get("days", 30, type=int)
    return jsonify({"followups": decisions.pending_followups(days)})


@life_admin_bp.route("/friday/finance/stock", methods=["POST"])
def finance_stock():
    data = request.get_json(silent=True) or {}
    if not finance:
        return jsonify({"error": "unavailable"}), 503
    symbol = data.get("symbol", "")
    if not symbol:
        return jsonify({"error": "symbol required"}), 400
    return jsonify(finance.get_stock_price(symbol))


@life_admin_bp.route("/friday/finance/portfolio", methods=["POST"])
def finance_portfolio():
    data = request.get_json(silent=True) or {}
    if not finance:
        return jsonify({"error": "unavailable"}), 503
    return jsonify(finance.portfolio_check(data.get("symbols", [])))


@life_admin_bp.route("/friday/finance/crypto", methods=["POST"])
def finance_crypto():
    data = request.get_json(silent=True) or {}
    if not finance:
        return jsonify({"error": "unavailable"}), 503
    return jsonify(finance.crypto_prices(data.get("coins", [])))


@life_admin_bp.route("/friday/finance/brief")
def finance_brief():
    if not finance:
        return jsonify({"error": "unavailable"}), 503
    return jsonify({"brief": finance.finance_brief()})


@life_admin_bp.route("/friday/legal/analyze", methods=["POST"])
def legal_analyze():
    data = request.get_json(silent=True) or {}
    if not legal:
        return jsonify({"error": "unavailable"}), 503
    return jsonify(legal.analyze_contract(data.get("text", "")))


@life_admin_bp.route("/friday/legal/red-flags", methods=["POST"])
def legal_red_flags():
    data = request.get_json(silent=True) or {}
    if not legal:
        return jsonify({"error": "unavailable"}), 503
    return jsonify({"red_flags": legal.find_red_flags(data.get("text", ""))})


@life_admin_bp.route("/friday/legal/simplify", methods=["POST"])
def legal_simplify():
    data = request.get_json(silent=True) or {}
    if not legal:
        return jsonify({"error": "unavailable"}), 503
    return jsonify({"simplified": legal.simplify_clause(data.get("clause", ""))})


@life_admin_bp.route("/friday/reading/index", methods=["POST"])
def reading_index():
    data = request.get_json(silent=True) or {}
    if not reading_mem:
        return jsonify({"error": "unavailable"}), 503
    url = data.get("url", "")
    if not url:
        return jsonify({"error": "url required"}), 400
    return jsonify(reading_mem.index_url(url, data.get("title", "")))


@life_admin_bp.route("/friday/reading/search")
def reading_search():
    if not reading_mem:
        return jsonify({"results": []})
    query = request.args.get("q", "")
    return jsonify({"results": reading_mem.search_reading(query)})


@life_admin_bp.route("/friday/social/person", methods=["POST"])
def social_person():
    data = request.get_json(silent=True) or {}
    if not social:
        return jsonify({"error": "unavailable"}), 503
    name = data.get("name", "")
    if not name:
        return jsonify({"error": "name required"}), 400
    return jsonify(social.person_brief(name, data.get("company", ""), data.get("context", "")))


@life_admin_bp.route("/friday/social/company", methods=["POST"])
def social_company():
    data = request.get_json(silent=True) or {}
    if not social:
        return jsonify({"error": "unavailable"}), 503
    return jsonify(social.company_brief(data.get("company", "")))


@life_admin_bp.route("/friday/tutor/explain", methods=["POST"])
def tutor_explain():
    data = request.get_json(silent=True) or {}
    if not tutor:
        return jsonify({"error": "unavailable"}), 503
    return jsonify({"explanation": tutor.explain(data.get("topic", ""), data.get("level", "auto"))})


@life_admin_bp.route("/friday/tutor/socratic", methods=["POST"])
def tutor_socratic():
    data = request.get_json(silent=True) or {}
    if not tutor:
        return jsonify({"error": "unavailable"}), 503
    return jsonify({"response": tutor.socratic_mode(
        data.get("topic", ""), data.get("prior_exchange", ""))})


@life_admin_bp.route("/friday/tutor/flashcards", methods=["POST"])
def tutor_flashcards():
    data = request.get_json(silent=True) or {}
    if not tutor:
        return jsonify({"error": "unavailable"}), 503
    return jsonify({"cards": tutor.flashcard_session(data.get("topic", ""), data.get("n_cards", 10))})


@life_admin_bp.route("/friday/tutor/review-card", methods=["POST"])
def tutor_review_card():
    data = request.get_json(silent=True) or {}
    if not tutor:
        return jsonify({"error": "unavailable"}), 503
    return jsonify(tutor.review_card(
        data.get("topic", ""), data.get("question", ""), bool(data.get("correct", False))))


@life_admin_bp.route("/friday/tutor/due-cards")
def tutor_due_cards():
    if not tutor:
        return jsonify({"cards": []})
    topic = request.args.get("topic", "")
    limit = request.args.get("limit", 10, type=int)
    return jsonify({"cards": tutor.due_cards(topic, limit)})


@life_admin_bp.route("/friday/tutor/quiz", methods=["POST"])
def tutor_quiz():
    data = request.get_json(silent=True) or {}
    if not tutor:
        return jsonify({"error": "unavailable"}), 503
    return jsonify(tutor.quiz_me(data.get("topic", ""), data.get("difficulty", "medium")))


@life_admin_bp.route("/friday/tutor/language-lesson", methods=["POST"])
def tutor_language_lesson():
    data = request.get_json(silent=True) or {}
    if not tutor:
        return jsonify({"error": "unavailable"}), 503
    return jsonify(tutor.language_lesson(data.get("language", ""), data.get("lesson_type", "vocabulary")))


@life_admin_bp.route("/friday/tutor/study-plan", methods=["POST"])
def tutor_study_plan():
    data = request.get_json(silent=True) or {}
    if not tutor:
        return jsonify({"error": "unavailable"}), 503
    return jsonify(tutor.study_plan(
        data.get("subject", ""), data.get("goal", ""), data.get("weeks", 4)))


@life_admin_bp.route("/friday/tutor/explain-error", methods=["POST"])
def tutor_explain_error():
    data = request.get_json(silent=True) or {}
    if not tutor:
        return jsonify({"error": "unavailable"}), 503
    return jsonify({"explanation": tutor.explain_error(
        data.get("error_message", ""), data.get("language", "python"))})


@life_admin_bp.route("/friday/plan", methods=["POST"])
def hierarchical_plan():
    data = request.get_json(silent=True) or {}
    if not hierarchical:
        return jsonify({"error": "unavailable"}), 503
    goal = data.get("goal", "")
    if not goal:
        return jsonify({"error": "goal required"}), 400
    return jsonify(hierarchical.plan(goal, data.get("depth", 4)))


@life_admin_bp.route("/friday/plan/track", methods=["POST"])
def hierarchical_plan_and_track():
    data = request.get_json(silent=True) or {}
    if not hierarchical:
        return jsonify({"error": "unavailable"}), 503
    goal = data.get("goal", "")
    if not goal:
        return jsonify({"error": "goal required"}), 400
    return jsonify(hierarchical.plan_and_track(goal, data.get("depth", 4)))
