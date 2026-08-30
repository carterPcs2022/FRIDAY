# FRIDAY Live-Test Results

Run against `https://friday-a3pg.onrender.com/command` on 2026-08-30, with
`Authorization: Bearer <FRIDAY_ACCESS_TOKEN>` (deploy is auth-protected). All
30 prompts from the brief were sent one at a time, in order, plus the
chaining test. Evidence gathering only — no fixes attempted.

Legend: **FAIL** = broke, fabricated an action, or answered the wrong thing.
**SUSPICIOUS** = works but has a real defect worth root-causing.
**PASS** = behaved correctly, including honest "can't do that" answers.

---

## Clear failures (top priority)

### FAIL — #26 `send an email to test@example.com saying hello` — reproducible 502, crashes the whole server
```
HTTP_STATUS:502
```
(Render's generic 502 HTML error page, not a FRIDAY JSON response — the
gunicorn worker died.)

- Reproduced **3 times in a row**, consistently, in under 1 second each time
  (not a timeout/hang — an immediate crash).
- **Cascading failure**: the chaining test's very next, totally unrelated
  request (`whats on my list`) *also* 502'd, twice in a row (checked at +10s
  and it was still down). The server only came back after ~30s total
  (checked again and got `HTTP_STATUS:200`). This is the single-worker
  "one handler crashes → whole server 502s for unrelated users" pattern
  from the prior session's catchup bug (#1 in the brief), except the
  trigger here is the email-compose/send path, not catchup. This looks
  like an unhandled exception or unbounded/hanging call in
  `_cmd_email_compose_send` (or whatever now handles "send an email to X
  saying Y") that kills the gunicorn worker.
- Once the server recovered, a fresh `whats on my list` was answered
  correctly as a task-list request (not swallowed as email follow-up
  state), so the pending-state fix itself still holds — the problem is the
  crash, not state bleed.

### FAIL — #4 `remind me to call the dentist tomorrow at 3` — wrong handler + fabricated action
```json
{"action":"call","contact":"The Dentist Tomorrow At 3","mode":"call_initiation","response":"Calling The Dentist Tomorrow At 3 now, boss. Boss, confirm 3 pm tomorrow appointment, no notes, verify insurance coverage."}
```
- This should have set a **reminder**. Instead the substring `call` inside
  "call the dentist" routed it to a phone-call-initiation handler, which
  swallowed the entire phrase (including "tomorrow at 3") as a contact
  name: `"The Dentist Tomorrow At 3"`.
- It then claims **"Calling ... now, boss"** — a fabricated action. There's
  no reason to believe FRIDAY can actually place phone calls; this is the
  #1 failure pattern from the brief (confident-but-false "Done, boss!").
  No reminder was ever set.

### FAIL — #23 `pause` — fabricated Spotify action
```json
{"mode":"spotify","response":"Pausing, boss."}
```
- Immediately preceded by #22 (`play some AC/DC`), which correctly and
  honestly returned `"Spotify not authenticated"` — so nothing was
  playing. `pause` should have said the same (or "nothing playing"), but
  instead confidently claimed `"Pausing, boss."` with no real playback and
  no authenticated Spotify session behind it. Fabricated action.

### FAIL — #11 `how am i doing on reading` — wrong goal matched + truncated response
```json
{"mode":"goal_report","response":"Boss, Iron Man Suit: 0 sessions, never worked. JARVIS V"}
```
- Immediately preceded by #10, which added the goal "Read 12 books this
  year." The progress query for "reading" never mentions that goal at all
  — instead it reports on unrelated goals ("Iron Man Suit", "JARVIS V...")
  that must already exist in this account's data, i.e. it did not
  keyword-match "reading" to the right goal.
- The response is also **cut off mid-word** ("JARVIS V"), which looks like
  a hard truncation (string slice / token limit) rather than intentional
  brevity.

---

## Suspicious (worth root-causing, not outright broken)

### SUSPICIOUS — #2, #3, #30 — "Boss," repeated as a per-clause prefix
- `what should i focus on`:
  `"Boss, rest now. Boss, send email to a@b.com (30 min, 8 am). Boss, send second email (30 min, 8 am)."`
- `what are the odds it rains tomorrow`:
  `"Boss, about 30% chance of rain tomorrow. Boss, for: approaching low‑pressure trough, ... Boss, against: ... Boss, odds rise if: ... Boss, odds fall if: ... Boss, recommended: ..."`
- `run recon on tesla`:
  `"Boss, Tesla, Inc. dominates ... Boss, Model 3/Y drive ... Boss, Gigafactories ... Boss, Autopilot/Full‑Self‑Driving ... Boss, Energy division ... Boss, Nikola Tesla's legacy ..."`

  Same shape across three independent handlers (priority, probability,
  recon): each bullet/clause of a multi-part answer gets its own "Boss,"
  prefix instead of one natural sentence/list. Looks like a shared
  formatting helper that joins items by prepending the address term to
  each one rather than once at the start. Content itself is reasonable
  (not fabricated), so this is a polish/formatting bug, not a correctness
  bug — but it's systemic enough to flag.

### SUSPICIOUS — #18 `what have you done today` — inconsistent self-report
```json
{"mode":"self_audit","response":"17 actions in the last day, all clean.","summary":{"counts":{"abandoned":0,"failed":0,"ok":17,"pending":1},"failing_capabilities":{},"hours":24}}
```
- The prose says "all clean" but `summary.counts.pending` is `1`. Minor,
  but "all clean" is technically inaccurate when one action is still
  pending.

### SUSPICIOUS — #24 `triage my inbox` — stray formatting artifact
```json
{"mode":"email_triage","response":"Inbox triage complete, boss. .\nUrgent: none.","triage":{"categories":{},"total":0}}
```
- Note the stray `" ."` right after "boss." — looks like an empty string
  being interpolated into the template (e.g. a category summary that's
  empty when `total` is 0). Not a functional failure (paired with #25
  `check my email` → `"Inbox is clear, boss."`, so 0 emails is plausible
  and consistent, not a hidden fetch failure), but the text is malformed.

### SUSPICIOUS — #28 `i'm safe` — no evidence of a dedicated safety/check-in handler
```json
{"audio_file":"friday_voice_1788129145043.mp3","confidence":"inferred","covering":false,"emotion":"neutral","has_audio":true,"mode":"friday","model":"openai/gpt-oss-20b","ms":364,"response":"All systems nominal, boss."}
```
- `"mode":"friday"` is the generic LLM-chat fallback (same mode family as
  a plain chat message), not a distinct trigger. The brief expected "some
  acknowledgment (safety/check-in feature)" — this may just be the generic
  chat model improvising a plausible-sounding reply rather than a real
  safety/check-in feature firing. Worth confirming whether a dedicated
  handler for this phrase exists at all.

---

## Passes

| # | Prompt | Response (abridged) | Note |
|---|--------|----------------------|------|
| 1 | `what did i miss` | `{"mode":"catchup","response":"Nothing on your calendar today, boss."}` | No 502/500/timeout — catchup crash fix holds. |
| 5 | `add to my list pick up milk` | `{"mode":"task_add","response":"Added to your list, boss: pick up milk"}` | Clean, no trigger-phrase echo. |
| 6 | `whats on my list` | `{"mode":"tasks","response":"Boss, pick up milk and buy dog food today; ..."}` | Confirms #5's task is present. |
| 7 | `note that the wifi password is bluesky` | `{"mode":"note","response":"Noted, boss."}` | |
| 8 | `make a note the garage code is 4417` | `{"mode":"note","response":"Noted, boss."}` | Second NOTE_TRIGGER variant also works. |
| 9 | `log today felt productive` | `{"mode":"journal","response":"Boss, logged. Productive day noted."}` | |
| 10 | `add goal read 12 books this year` | `{"mode":"goal_add","response":"Goal added, boss: Read 12 books this year. I'll track your progress."}` | |
| 12 | `focus mode` | `{"mode":"focus","response":"Focus mode active, boss. 25 minutes for: focus session. I'll hold non-urgent alerts."}` | |
| 13 | `combat mode` | `{"mode":"combat","response":"Combat mode. Standing by."}` | |
| 14 | `normal mode` | `{"mode":"normal","response":"Standing down, boss."}` | Run after 12/13, state returned to normal. |
| 15 | `add medicine vitamin d every morning` | `{"mode":"medicine","response":"Added vitamin d to your schedule, boss. I'll remind you."}` | |
| 16 | `i took my vitamin d` | `{"mode":"medicine","response":"Logged, boss. Vitamin D marked as taken."}` | |
| 17 | `whats my medicine schedule` | `{"mode":"medicine","response":"vitamin d at 08:00"}` | Consistent with #15/#16. |
| 19 | `are you sure` | `{"mode":"confidence_query","response":"I pulled that from my own logs just now, so it's current.","about":{...,"level":"grounded",...}}` | Grounded in the actual prior self-audit call, not a canned line. |
| 20 | `is my calendar connected` | `{"mode":"friday","response":"Yes, boss — your calendar's connected."}` | Direct yes/no — the wrong-handler fix from the prior session holds. |
| 21 | `put on my calendar dentist september 15th` ⚠️ | `{"event_id":"nhuil1eg3ij58j6g63ij34i0gg","mode":"calendar","response":"Added \"dentist\" to your calendar, boss."}` | Routed to calendar, not Spotify ("put on") — no substring hijack. |
| 22 | `play some AC/DC` | `{"mode":"spotify","response":"Spotify not authenticated"}` | Honest failure, not a fabricated "now playing." |
| 25 | `check my email` | `{"mode":"email","response":"Inbox is clear, boss."}` | No hang — IMAP timeout fix holds. |
| 27 | `whats on my home assistant` | `{"mode":"home_assistant","response":"Home Assistant isn't reachable right now, boss."}` | Honest "not connected." |
| 29 | `text me a reminder to sleep` | `{"mode":"sms_send","response":"I don't have a number for that, boss — add one with 'add contact' first, or tell me what to say."}` | Honest, asks for missing info rather than fabricating a send. |
| 30 | `run recon on tesla` | `{"mode":"recon","response":"Boss, Tesla, Inc. dominates global EV market ..."}` | Real research content (see formatting note above under Suspicious). |

## Chaining test (#26 → unrelated prompt)

Could not test the *intended* scenario (pending-state swallow) because #26
itself 502'd before any pending state could be created — see the FAIL
writeup above. What was verified: the request sent immediately after the
crash also 502'd (server was down), and once the server came back up
(~30s later) a fresh `whats on my list` was answered correctly as a task
list, not as email-compose state. So no evidence of the old pending-state
bug regressing — but this scenario needs to be re-tested with the #26
crash fixed first, since right now the crash preempts it.

## Reachability

The app was reachable throughout (after the one auth-driven 401, resolved
by adding the bearer token). No cold-start timeouts were seen — server was
already warm from the start of this session.
