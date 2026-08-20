"""tests/test_memory_hub.py — core/memory_hub.py's unified recall()/
remember(), the V3 Phase 2 deliverable: one ranked read path and one
write dispatcher over the five previously-independent memory stores
(core/friday_memory.py, services/second_brain.py,
services/reading_memory.py, services/friday_journal.py,
services/friday_continuity.py), without migrating any of their data.
"""
from unittest import mock

from core import memory_hub


class TestOverlapScore:
    def test_counts_shared_words(self):
        assert memory_hub.overlap_score({"budget", "review"}, "quarterly budget review") == 2

    def test_no_overlap_is_zero(self):
        assert memory_hub.overlap_score({"budget"}, "completely unrelated text") == 0

    def test_case_insensitive(self):
        assert memory_hub.overlap_score({"budget"}, "BUDGET meeting") == 1


class TestRecall:
    def test_empty_query_returns_nothing(self):
        assert memory_hub.recall("") == []
        assert memory_hub.recall("   ") == []

    def test_pulls_and_tags_facts_and_notes(self):
        with mock.patch("core.friday_memory.get_facts", return_value=["the sky is blue", "budget is due Friday"]), \
             mock.patch("core.friday_memory.get_notes", return_value=[{"content": "unrelated note", "context": "", "ts": "t1"}]), \
             mock.patch("services.second_brain.second_brain.recall", return_value=[]), \
             mock.patch("services.friday_continuity.continuity.get_unresolved_topics", return_value=[]), \
             mock.patch("services.wisdom.get_wisdom_context", return_value=""):
            hits = memory_hub.recall("budget")

        assert len(hits) == 1
        assert hits[0]["source"] == "facts"
        assert "budget" in hits[0]["text"]

    def test_ranks_by_score_across_sources(self):
        with mock.patch("core.friday_memory.get_facts", return_value=["project x deadline moved"]), \
             mock.patch("core.friday_memory.get_notes", return_value=[]), \
             mock.patch(
                 "services.second_brain.second_brain.recall",
                 return_value=[{"summary": "project x deadline and scope both changed", "ts": "t2"}],
             ), \
             mock.patch("services.friday_continuity.continuity.get_unresolved_topics", return_value=[]), \
             mock.patch("services.wisdom.get_wisdom_context", return_value=""):
            hits = memory_hub.recall("project x deadline")

        # The second_brain hit shares more query words ("project","x","deadline")
        # than the facts hit ("project","x","deadline" too, but shorter text) --
        # both should be present and returned in descending score order.
        assert len(hits) == 2
        assert hits[0]["score"] >= hits[1]["score"]
        assert {h["source"] for h in hits} == {"facts", "second_brain"}

    def test_folds_in_wisdom_context_with_source_tags(self):
        wisdom_text = (
            "Past decisions relevant to this: chose Postgres over Mongo\n"
            "Previously read on this: Postgres scaling guide"
        )
        with mock.patch("core.friday_memory.get_facts", return_value=[]), \
             mock.patch("core.friday_memory.get_notes", return_value=[]), \
             mock.patch("services.second_brain.second_brain.recall", return_value=[]), \
             mock.patch("services.friday_continuity.continuity.get_unresolved_topics", return_value=[]), \
             mock.patch("services.wisdom.get_wisdom_context", return_value=wisdom_text):
            hits = memory_hub.recall("postgres")

        sources = {h["source"] for h in hits}
        assert "decisions" in sources
        assert "reading" in sources

    def test_unresolved_topics_scored_and_tagged(self):
        with mock.patch("core.friday_memory.get_facts", return_value=[]), \
             mock.patch("core.friday_memory.get_notes", return_value=[]), \
             mock.patch("services.second_brain.second_brain.recall", return_value=[]), \
             mock.patch(
                 "services.friday_continuity.continuity.get_unresolved_topics",
                 return_value=[{"topic": "moving apartments", "mentions": 3, "last_mentioned": "t3"}],
             ), \
             mock.patch("services.wisdom.get_wisdom_context", return_value=""):
            hits = memory_hub.recall("moving apartments")

        assert len(hits) == 1
        assert hits[0]["source"] == "continuity"
        assert "moving apartments" in hits[0]["text"]

    def test_one_store_failing_does_not_break_the_others(self):
        """A Turso hiccup (or any other failure) inside one store's
        recall must not take the other four down with it -- same "one
        broken piece can't sink the whole request" convention this
        codebase uses everywhere else. Caught by this test during
        Phase 2 development: the first draft only guarded each store's
        *import*, not its actual query call."""
        with mock.patch("core.friday_memory.get_facts", return_value=["budget note here"]), \
             mock.patch("core.friday_memory.get_notes", return_value=[]), \
             mock.patch("services.second_brain.second_brain.recall", side_effect=RuntimeError("turso down")), \
             mock.patch("services.friday_continuity.continuity.get_unresolved_topics", return_value=[]), \
             mock.patch("services.wisdom.get_wisdom_context", return_value=""):
            hits = memory_hub.recall("budget")

        assert len(hits) == 1
        assert hits[0]["source"] == "facts"


class TestRemember:
    def test_fact(self):
        with mock.patch("core.friday_memory.save_fact") as save_fact:
            result = memory_hub.remember("the sky is blue", kind="fact")
        save_fact.assert_called_once_with("the sky is blue")
        assert result == {"stored": True, "kind": "fact"}

    def test_note(self):
        with mock.patch("core.friday_memory.save_note") as save_note:
            result = memory_hub.remember("call the dentist", kind="note", context="from a reminder")
        assert save_note.called
        (note,), _ = save_note.call_args
        assert note["content"] == "call the dentist"
        assert note["context"] == "from a reminder"
        assert "ts" in note
        assert result["kind"] == "note"

    def test_reading(self):
        with mock.patch(
            "services.reading_memory.reading_mem.index_url",
            return_value={"url": "http://x.com", "title": "X", "ts": "t1"},
        ) as index_url:
            result = memory_hub.remember("http://x.com", kind="reading", title="X")
        index_url.assert_called_once_with("http://x.com", title="X")
        assert result["stored"] is True
        assert result["kind"] == "reading"

    def test_reading_error_not_reported_as_stored(self):
        with mock.patch(
            "services.reading_memory.reading_mem.index_url",
            return_value={"error": "Could not fetch URL"},
        ):
            result = memory_hub.remember("http://bad-url", kind="reading")
        assert result["stored"] is False

    def test_journal(self):
        with mock.patch(
            "services.friday_journal.journal.log_entry",
            return_value={"logged": True, "entry": {"content": "good day", "mood": "happy"}},
        ) as log_entry:
            result = memory_hub.remember("good day", kind="journal", mood="happy")
        log_entry.assert_called_once_with("good day", mood="happy")
        assert result["kind"] == "journal"

    def test_topic(self):
        with mock.patch("services.friday_continuity.continuity.record_topic") as record_topic:
            memory_hub.remember("apartment search", kind="topic", resolved=True)
        record_topic.assert_called_once_with("apartment search", resolved=True)

    def test_general_defaults_to_second_brain(self):
        with mock.patch(
            "services.second_brain.second_brain.ingest",
            return_value={"id": "abc123", "summary": "s", "stored": True},
        ) as ingest:
            result = memory_hub.remember("some long article text")
        ingest.assert_called_once_with("some long article text", source="", tags=None)
        assert result["kind"] == "general"

    def test_unknown_kind_falls_back_to_general(self):
        with mock.patch(
            "services.second_brain.second_brain.ingest",
            return_value={"id": "x", "summary": "s"},
        ) as ingest:
            memory_hub.remember("content", kind="not-a-real-kind")
        assert ingest.called


class TestMemoryRoutes:
    def test_recall_route_requires_query(self, client):
        resp = client.get("/friday/memory/recall")
        assert resp.status_code == 400

    def test_recall_route_calls_hub(self, client):
        with mock.patch("core.memory_hub.recall", return_value=[{"text": "x", "source": "facts", "score": 1, "ts": None}]) as recall:
            resp = client.get("/friday/memory/recall?q=budget&limit=3")
        assert resp.status_code == 200
        recall.assert_called_once_with("budget", limit=3)
        assert resp.get_json()["results"][0]["source"] == "facts"

    def test_remember_route_requires_content(self, client):
        resp = client.post("/friday/memory/remember", json={})
        assert resp.status_code == 400

    def test_remember_route_dispatches_kind_and_extra_fields(self, client):
        with mock.patch("core.memory_hub.remember", return_value={"stored": True, "kind": "journal"}) as remember:
            resp = client.post(
                "/friday/memory/remember",
                json={"content": "good day", "kind": "journal", "mood": "happy"},
            )
        assert resp.status_code == 200
        remember.assert_called_once_with("good day", kind="journal", mood="happy")
