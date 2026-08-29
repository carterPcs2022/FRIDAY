"""tests/test_task_add.py — _cmd_task_add's trigger phrase must not end
up inside the stored task.

Confirmed live: the tool router rewrote "i need to pick up dog food at
some point" into "add to my list dog food", and extraction handed that
whole string to the model, which echoed it straight back:

    "Added to your list, boss: add to my list dog food"

"Reply with just the task. No extra text." wasn't enough to stop a
small model from including words that were sitting right there in its
own input. Stripping the matched trigger before extraction removes the
possibility structurally -- the phrase isn't in what the model sees,
so it can't hand it back.
"""
from unittest import mock

import pytest

import server


def _think(text):
    return {"response": text, "model": "test", "ms": 1}


class TestTriggerIsStrippedBeforeExtraction:
    def test_the_production_case(self, app):
        """The exact router rewrite that produced the bug."""
        fake_brain = mock.Mock()
        fake_brain.think.return_value = _think("dog food")

        with app.test_request_context(), mock.patch("server.friday_brain", fake_brain), \
             mock.patch("server.add_task"):
            prompt = "add to my list dog food"
            result = server._cmd_task_add(prompt, prompt.lower())

        sent = fake_brain.think.call_args[0][0]
        assert "add to my list" not in sent.lower()
        assert "dog food" in sent
        assert result.get_json()["response"] == "Added to your list, boss: dog food"

    @pytest.mark.parametrize("trigger,prompt", [
        ("add to my list", "add to my list buy milk"),
        ("add task", "add task call the dentist"),
        ("todo:", "todo: renew the passport"),
        ("don't forget to", "don't forget to water the plants"),
        ("put on my list", "put on my list new tires"),
    ])
    def test_every_trigger_is_stripped(self, app, trigger, prompt):
        fake_brain = mock.Mock()
        fake_brain.think.return_value = _think("something")

        with app.test_request_context(), mock.patch("server.friday_brain", fake_brain), \
             mock.patch("server.add_task"):
            server._cmd_task_add(prompt, prompt.lower())

        sent = fake_brain.think.call_args[0][0]
        assert trigger not in sent.lower()

    def test_only_the_first_occurrence_is_stripped(self, app):
        """A genuine task about the trigger phrase itself keeps its own
        words -- this is a targeted fix for the router's echo, not a
        blanket filter."""
        fake_brain = mock.Mock()
        fake_brain.think.return_value = _think("something")

        with app.test_request_context(), mock.patch("server.friday_brain", fake_brain), \
             mock.patch("server.add_task"):
            prompt = "add to my list to add to my list of chores every week"
            server._cmd_task_add(prompt, prompt.lower())

        sent = fake_brain.think.call_args[0][0]
        assert "add to my list of chores every week" in sent

    def test_the_task_is_still_saved(self, app):
        fake_brain = mock.Mock()
        fake_brain.think.return_value = _think("dog food")
        added = mock.Mock()

        with app.test_request_context(), mock.patch("server.friday_brain", fake_brain), \
             mock.patch("server.add_task", added):
            prompt = "add to my list dog food"
            server._cmd_task_add(prompt, prompt.lower())

        added.assert_called_once_with("dog food")

    def test_a_non_triggering_prompt_is_declined(self, app):
        with app.test_request_context():
            assert server._cmd_task_add("what's the weather", "what's the weather") is None
