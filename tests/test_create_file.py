"""tests/test_create_file.py — the "create a file" feature: generated
files are stored the same JSON+Turso way core/friday_memory.py already
stores notes (never as a loose file on Render's disk), the /command
dispatcher parses a name/content out of the prompt, and a name spoken
in a chat prompt never turns into a path-traversal write once
services/friday_gmail.py materializes it as an email attachment.
"""
from unittest import mock

import server
from core import friday_memory


class TestGeneratedFileStore:
    def test_save_and_get_by_name_round_trips(self, tmp_path, monkeypatch):
        monkeypatch.setattr(friday_memory, "FILES_FILE", tmp_path / "friday_files.json")
        monkeypatch.setattr(friday_memory.turso, "is_configured", lambda: False)

        friday_memory.save_generated_file({"name": "todo.txt", "content": "milk\neggs"})

        entry = friday_memory.get_generated_file("todo.txt")
        assert entry is not None
        assert entry["content"] == "milk\neggs"

    def test_lookup_is_case_insensitive(self, tmp_path, monkeypatch):
        monkeypatch.setattr(friday_memory, "FILES_FILE", tmp_path / "friday_files.json")
        monkeypatch.setattr(friday_memory.turso, "is_configured", lambda: False)

        friday_memory.save_generated_file({"name": "Todo.txt", "content": "x"})

        assert friday_memory.get_generated_file("todo.txt") is not None
        assert friday_memory.get_generated_file("TODO.TXT") is not None

    def test_later_file_with_same_name_supersedes_earlier(self, tmp_path, monkeypatch):
        monkeypatch.setattr(friday_memory, "FILES_FILE", tmp_path / "friday_files.json")
        monkeypatch.setattr(friday_memory.turso, "is_configured", lambda: False)

        friday_memory.save_generated_file({"name": "todo.txt", "content": "old"})
        friday_memory.save_generated_file({"name": "todo.txt", "content": "new"})

        assert friday_memory.get_generated_file("todo.txt")["content"] == "new"

    def test_unknown_name_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(friday_memory, "FILES_FILE", tmp_path / "friday_files.json")
        monkeypatch.setattr(friday_memory.turso, "is_configured", lambda: False)

        assert friday_memory.get_generated_file("nope.txt") is None

    def test_empty_name_returns_none_without_matching_blank_entries(self, tmp_path, monkeypatch):
        monkeypatch.setattr(friday_memory, "FILES_FILE", tmp_path / "friday_files.json")
        monkeypatch.setattr(friday_memory.turso, "is_configured", lambda: False)

        assert friday_memory.get_generated_file("") is None
        assert friday_memory.get_generated_file(None) is None


class TestSafeFilename:
    def test_strips_path_traversal(self):
        assert ".." not in server._safe_filename("../../etc/passwd")
        assert "/" not in server._safe_filename("../../etc/passwd")

    def test_strips_backslashes_and_html(self):
        result = server._safe_filename('..\\evil<script>alert(1)</script>')
        assert "\\" not in result
        assert "<" not in result and ">" not in result

    def test_leaves_an_ordinary_name_alone(self):
        assert server._safe_filename("shopping list") == "shopping list"


class TestCmdCreateFile:
    def test_no_trigger_returns_none(self, app):
        with app.test_request_context():
            result = server._cmd_create_file("what time is it", "what time is it")
        assert result is None

    def test_explicit_name_and_content_are_used_directly(self, app, tmp_path, monkeypatch):
        monkeypatch.setattr(friday_memory, "FILES_FILE", tmp_path / "friday_files.json")
        monkeypatch.setattr(friday_memory.turso, "is_configured", lambda: False)
        with app.test_request_context(), mock.patch("server.friday_brain", None):
            prompt = "create a file called shopping list: milk, eggs, bread"
            result = server._cmd_create_file(prompt, prompt.lower())

        assert result is not None
        body = result.get_json()
        assert body["mode"] == "create_file"
        assert body["file"]["name"] == "shopping list.txt"
        assert body["file"]["content"] == "milk, eggs, bread"

    def test_no_explicit_content_drafts_via_friday_brain(self, app, tmp_path, monkeypatch):
        monkeypatch.setattr(friday_memory, "FILES_FILE", tmp_path / "friday_files.json")
        monkeypatch.setattr(friday_memory.turso, "is_configured", lambda: False)
        fake_brain = mock.Mock()
        fake_brain.think.return_value = {"response": "Drafted content."}
        with app.test_request_context(), mock.patch("server.friday_brain", fake_brain):
            prompt = "create a file called ideas"
            result = server._cmd_create_file(prompt, prompt.lower())

        assert result is not None
        body = result.get_json()
        assert body["file"]["content"] == "Drafted content."
        fake_brain.think.assert_called_once()

    def test_no_name_given_derives_one_from_content(self, app, tmp_path, monkeypatch):
        monkeypatch.setattr(friday_memory, "FILES_FILE", tmp_path / "friday_files.json")
        monkeypatch.setattr(friday_memory.turso, "is_configured", lambda: False)
        with app.test_request_context(), mock.patch("server.friday_brain", None):
            prompt = "create a file: quarterly numbers are up"
            result = server._cmd_create_file(prompt, prompt.lower())

        assert result is not None
        name = result.get_json()["file"]["name"]
        assert name.endswith(".txt")
        assert name != ".txt"

    def test_path_traversal_name_is_sanitized_before_storage(self, app, tmp_path, monkeypatch):
        monkeypatch.setattr(friday_memory, "FILES_FILE", tmp_path / "friday_files.json")
        monkeypatch.setattr(friday_memory.turso, "is_configured", lambda: False)
        with app.test_request_context(), mock.patch("server.friday_brain", None):
            prompt = "create a file called ../../etc/passwd: pwned"
            result = server._cmd_create_file(prompt, prompt.lower())

        name = result.get_json()["file"]["name"]
        assert ".." not in name
        assert "/" not in name


class TestClarifyHelper:
    def test_returns_structured_options_the_hud_can_render_as_chips(self, app):
        with app.test_request_context():
            result = server._clarify(
                "some prompt", "Which one, boss?",
                [{"label": "A", "value": "a"}, {"label": "B", "value": "b"}],
                "test_mode",
            )

        body = result.get_json()
        assert body["mode"] == "test_mode"
        assert body["response"] == "Which one, boss?"
        assert body["clarify"] == {
            "question": "Which one, boss?",
            "options": [{"label": "A", "value": "a"}, {"label": "B", "value": "b"}],
        }


class TestCmdFileRecall:
    def test_no_trigger_returns_none(self, app):
        with app.test_request_context():
            result = server._cmd_file_recall("what time is it", "what time is it")
        assert result is None

    def test_finds_a_previously_created_file(self, app, tmp_path, monkeypatch):
        monkeypatch.setattr(friday_memory, "FILES_FILE", tmp_path / "friday_files.json")
        monkeypatch.setattr(friday_memory.turso, "is_configured", lambda: False)
        friday_memory.save_generated_file({"name": "todo.txt", "content": "milk"})

        with app.test_request_context():
            prompt = "open the file called todo.txt"
            result = server._cmd_file_recall(prompt, prompt.lower())

        assert result is not None
        body = result.get_json()
        assert body["mode"] == "file_recall"
        assert body["file"]["content"] == "milk"

    def test_missing_file_reports_not_found_instead_of_crashing(self, app, tmp_path, monkeypatch):
        monkeypatch.setattr(friday_memory, "FILES_FILE", tmp_path / "friday_files.json")
        monkeypatch.setattr(friday_memory.turso, "is_configured", lambda: False)

        with app.test_request_context():
            prompt = "open the file called nonexistent.txt"
            result = server._cmd_file_recall(prompt, prompt.lower())

        assert result is not None
        body = result.get_json()
        assert "file" not in body
        assert "nonexistent.txt" in body["response"]

    def test_no_name_given_and_nothing_saved_asks_which_file(self, app, tmp_path, monkeypatch):
        monkeypatch.setattr(friday_memory, "FILES_FILE", tmp_path / "friday_files.json")
        monkeypatch.setattr(friday_memory.turso, "is_configured", lambda: False)

        with app.test_request_context():
            prompt = "show me the file"
            result = server._cmd_file_recall(prompt, prompt.lower())

        assert result is not None
        body = result.get_json()
        assert "which file" in body["response"].lower()
        assert "clarify" not in body

    def test_no_name_given_but_files_exist_offers_clickable_options(self, app, tmp_path, monkeypatch):
        monkeypatch.setattr(friday_memory, "FILES_FILE", tmp_path / "friday_files.json")
        monkeypatch.setattr(friday_memory.turso, "is_configured", lambda: False)
        friday_memory.save_generated_file({"name": "todo.txt", "content": "milk"})
        friday_memory.save_generated_file({"name": "ideas.txt", "content": "..."})

        with app.test_request_context():
            prompt = "show me the file"
            result = server._cmd_file_recall(prompt, prompt.lower())

        assert result is not None
        body = result.get_json()
        assert body["mode"] == "file_recall"
        assert "clarify" in body
        names = {opt["value"] for opt in body["clarify"]["options"]}
        assert names == {"todo.txt", "ideas.txt"}
        # Most recent first -- picking "the file" with no name given should
        # offer the most likely match up top, not alphabetical/insertion order.
        assert body["clarify"]["options"][0]["value"] == "ideas.txt"


class TestEmailAttachmentResolvesGeneratedFile:
    def test_resolve_attachment_materializes_generated_file_content(self, tmp_path, monkeypatch):
        monkeypatch.setattr(friday_memory, "FILES_FILE", tmp_path / "friday_files.json")
        monkeypatch.setattr(friday_memory.turso, "is_configured", lambda: False)
        friday_memory.save_generated_file({"name": "todo.txt", "content": "milk, eggs"})

        from services.friday_gmail import FridayGmail
        gmail = FridayGmail.__new__(FridayGmail)  # skip __init__'s IMAP/env setup
        resolved = gmail._resolve_attachment("todo.txt")

        assert resolved is not None
        assert resolved.read_text() == "milk, eggs"

    def test_resolve_attachment_returns_none_for_unknown_ref(self, tmp_path, monkeypatch):
        monkeypatch.setattr(friday_memory, "FILES_FILE", tmp_path / "friday_files.json")
        monkeypatch.setattr(friday_memory.turso, "is_configured", lambda: False)

        from services.friday_gmail import FridayGmail
        gmail = FridayGmail.__new__(FridayGmail)
        assert gmail._resolve_attachment("no-such-file-anywhere.txt") is None
