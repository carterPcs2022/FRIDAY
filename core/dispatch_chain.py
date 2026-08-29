"""core/dispatch_chain.py — the order FRIDAY tries her capabilities in.

This was 59 copies of

    result = _cmd_something(prompt, p_lower)
    if result is not None:
        return result

inline in server.py, and the repetition was not the problem. The problem
was that the order -- which is the single most behaviour-defining fact in
this system -- existed only as an emergent property of where each block
happened to sit in a 3,400-line file. Nothing named it, nothing tested
it, and nothing stopped a new handler being pasted in the wrong place.

Every dispatch bug on this branch was an ordering bug. Spotify's "put on"
swallowed "put on my calendar". The reminder handler took "remind me to
take my pills" before the medication tracker saw it. Both were fixed with
deferral guards computed against the very lists this file now makes
explicit.

Two chains, and the boundary between them is load-bearing:

  PRE_SPLIT   checked against the whole message, before it can be broken
              into segments. Lockdown and mayday belong here and nowhere
              else: they are about the message as a whole, and a
              multi-command message must not be able to smuggle one past
              them in a fragment -- nor fire one six times because six
              segments each contained the word.

  MAIN        everything else, tried in order against each segment.

Order within each list is exactly the order the inline chain ran in, and
tests/test_dispatch_chain.py pins it against a copy captured from the
source before this refactor. That test is the point of the file: it turns
"the order happens to be right" into "the order is asserted".

Handlers are named as strings and resolved against server.py once at
import, rather than imported here -- server.py imports this module, so
holding the functions themselves would be a cycle. Resolution happens at
boot and raises on a name that doesn't exist, so a typo or a deleted
handler fails immediately and loudly instead of silently dropping a
capability out of the chain.
"""

# Checked against the whole message, before splitting. Nothing may be
# added here without reading the note above -- this is the only part of
# the chain where being early is a safety property rather than a
# preference.
PRE_SPLIT = [
    "_cmd_lockdown_locked",
    "_cmd_lockdown_trigger",
    "_cmd_mayday",
    "_cmd_safety_near_miss",
    "_cmd_safe_checkin",
    "_cmd_security_screen",
]

# Tried in order. Earlier wins, so a vaguer trigger placed above a
# specific one silently steals it -- see _SPOTIFY_SHADOWED_TRIGGERS and
# _REMINDER_SHADOWED_TRIGGERS in server.py for the two that already
# happened, and tests/test_trigger_shadowing.py for the guard.
MAIN = [
    "_cmd_learn_voice_mode",
    "_cmd_dark_mode",
    "_cmd_capabilities",
    "_cmd_weather",
    "_cmd_news",
    "_cmd_translate",
    "_cmd_code_review",
    "_cmd_remember_this",
    "_cmd_people_brief",
    "_cmd_caller_id",
    "_cmd_call_initiate",
    "_cmd_sms_send",
    "_cmd_confidence_query",
    "_cmd_self_audit",
    "_cmd_catchup",
    "_cmd_focus",
    "_cmd_habit_log",
    "_cmd_journal",
    "_cmd_probability",
    "_cmd_recon",
    "_cmd_diagnostics",
    "_cmd_self_repair",
    "_cmd_cross_check",
    "_cmd_combat_mode",
    "_cmd_normal_mode",
    "_cmd_priority",
    "_cmd_travel",
    "_cmd_spotify_stop",
    "_cmd_spotify_play",
    "_cmd_calendar_add",
    "_cmd_goal_report",
    "_cmd_goal_add",
    "_cmd_goal_progress",
    "_cmd_email_draft",
    "_cmd_email_send",
    "_cmd_email_compose_send",
    "_cmd_email_triage",
    "_cmd_email_summary",
    "_cmd_note",
    "_cmd_create_file",
    "_cmd_file_recall",
    "_cmd_reminder",
    "_cmd_task_show",
    "_cmd_task_add",
    "_cmd_med_schedule",
    "_cmd_med_taken",
    "_cmd_med_skip",
    "_cmd_med_add",
    "_cmd_homekit",
    "_cmd_mac_app",
    "_cmd_ha_status",
    "_cmd_ha_toggle",
    "_cmd_jarvis_proxy",
]
