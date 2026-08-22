"""routes/knowledge.py — Weather, second brain, news, people, translate, code review routes, split out of the former
monolithic server.py. Registered onto the main Flask app in server.py
via app.register_blueprint(knowledge_bp); nothing here changes behavior,
only where the code lives.
"""
from flask import Blueprint, request, jsonify

from core.app_state import (
    friday_code,
    get_weather_brief,
    news_anchor,
    relationships,
    second_brain,
    translator,
)

knowledge_bp = Blueprint("knowledge", __name__)


@knowledge_bp.route("/friday/weather")
def weather_route():
    return jsonify({"weather": get_weather_brief(request.args.get("location", ""))})


@knowledge_bp.route("/friday/brain/ingest", methods=["POST"])
def brain_ingest():
    data = request.get_json(silent=True) or {}
    if not second_brain:
        return jsonify({"error": "unavailable"}), 503
    return jsonify(second_brain.ingest(data.get("content", ""), data.get("source", "")))


@knowledge_bp.route("/friday/brain/recall")
def brain_recall():
    if not second_brain:
        return jsonify({"results": []})
    return jsonify({"results": second_brain.recall(request.args.get("q", ""))})


@knowledge_bp.route("/friday/brain/digest")
def brain_digest():
    if not second_brain:
        return jsonify({"digest": ""})
    return jsonify({"digest": second_brain.daily_digest()})


@knowledge_bp.route("/friday/news/morning")
def news_morning():
    if not news_anchor:
        return jsonify({"brief": ""})
    return jsonify({"brief": news_anchor.morning_brief()})


@knowledge_bp.route("/friday/news/breaking")
def news_breaking():
    if not news_anchor:
        return jsonify({"news": ""})
    return jsonify({"news": news_anchor.breaking_news(request.args.get("topic", "AI"))})


@knowledge_bp.route("/friday/people/log", methods=["POST"])
def people_log():
    data = request.get_json(silent=True) or {}
    if not relationships:
        return jsonify({"error": "unavailable"}), 503
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    return jsonify(relationships.log_contact(name, data.get("notes", "")))


@knowledge_bp.route("/friday/people/attention")
def people_attention():
    if not relationships:
        return jsonify({"people": []})
    return jsonify({"people": relationships.who_needs_attention()})


@knowledge_bp.route("/friday/translate", methods=["POST"])
def translate_endpoint():
    data = request.get_json(silent=True) or {}
    if not translator:
        return jsonify({"error": "unavailable"}), 503
    return jsonify(translator.translate(data.get("text", ""), data.get("target", "English")))


@knowledge_bp.route("/friday/code/review", methods=["POST"])
def code_review():
    data = request.get_json(silent=True) or {}
    if not friday_code:
        return jsonify({"error": "unavailable"}), 503
    return jsonify(friday_code.quick_review(data.get("code", ""), data.get("language", "")))


@knowledge_bp.route("/friday/code/fix", methods=["POST"])
def code_fix():
    data = request.get_json(silent=True) or {}
    if not friday_code:
        return jsonify({"error": "unavailable"}), 503
    return jsonify(friday_code.fix(data.get("code", ""), data.get("error", "")))


@knowledge_bp.route("/friday/memory/recall")
def memory_recall():
    """core/memory_hub.py's unified recall -- searches facts, notes,
    second brain, reading history, journal, decisions, and continuity's
    unresolved topics in one call, ranked together. Distinct from
    /friday/brain/recall above, which only ever searched second_brain."""
    from core.memory_hub import recall
    query = request.args.get("q", "")
    if not query:
        return jsonify({"error": "q required"}), 400
    return jsonify({"results": recall(query, limit=int(request.args.get("limit", 8)))})


@knowledge_bp.route("/friday/memory/remember", methods=["POST"])
def memory_remember():
    """core/memory_hub.py's unified write dispatcher -- routes to
    whichever store's own write method fits `kind` (fact/note/reading/
    journal/topic/general). See that module's docstring for the mapping."""
    from core.memory_hub import remember
    data = request.get_json(silent=True) or {}
    content = data.get("content", "").strip()
    if not content:
        return jsonify({"error": "content required"}), 400
    kwargs = {k: v for k, v in data.items() if k not in ("content", "kind")}
    return jsonify(remember(content, kind=data.get("kind", "general"), **kwargs))
