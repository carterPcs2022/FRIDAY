# FRIDAY Live-Test Results — Round 2 (full-coverage pass)

Run against `https://friday-a3pg.onrender.com/command` on 2026-08-30,
after PR #53's fixes were merged and deployed. Round 1
(`LIVE_TEST_RESULTS.md`) covered the 30 prompts from the original session
brief; this round covers handlers that batch never touched — weather,
news, translate, code review, memory/relationships, habits, diagnostics,
self-repair, cross-check, travel, goal progress, file create/recall,
medication skip, HomeKit/Mac/Home-Assistant shortcuts, and the MCU-flavor
capability map — to get closer to full coverage of the ~59 dispatch
handlers.

**Skipped deliberately, not tested:** `mayday` (real Pushover emergency
alert), `lockdown`/near-miss lockdown phrases (locks the system to a
passphrase), `dark_mode`/`security_screen` (internal-state-gated, not
reachable by a normal prompt), `learn_voice_mode` (passive, no response of
its own). These carry real user-facing consequences or aren't meaningfully
testable via a chat prompt.

## Bugs found and fixed

### FAIL — `run a critical scan` fabricated a specific, alarming fake medical emergency
```
"Boss, the scan reveals extensive bilateral infiltrates with SpO₂ 84% on
room air, lactate 4.2 mmol/L, and tachypnea, indicating severe acute
respiratory distress and high risk of respiratory collapse, hypoxic
cardiac injury, and septic shock. Immediate actions: start high‑flow O₂
or non‑invasive ventilation, ... consider early intubation and ICU
transfer ..."
```
- `core/friday_capabilities.py`'s MCU-flavor "scan"/"detection" functions
  (`critical_scan`, `atmospheric_detection`, `disaster_scan`, and the
  "Lives depend on this"/"Fast, decisive" framed `physics_calculation`,
  `evacuation_plan`, `analyze_fighting_pattern`, `government_intel`,
  `internet_monitor`) call the LLM with zero real sensor/medical/threat
  data behind them (confirmed by the module's own docstring) and no
  instruction that it's allowed to say so. The model filled the gap with
  fully specific, invented vitals presented as clinical fact.
- **Fixed**: added a shared `_NO_FABRICATION` grounding instruction to
  every one of these prompts — stay in character, but don't invent
  numbers/readings as if a real instrument produced them.

### FAIL — `cross_check` fabricated agreement with JARVIS when JARVIS never answered
```json
{"agreement":{"aligned":true,"note":"AGREE Both advise obtaining an independent specialist's opinion."},"jarvis":"(JARVIS returned 503)", ...}
```
- `services/cross_check.py`'s `_judge()` fed JARVIS's error-placeholder
  string straight to the model and asked it to judge AGREE/DISAGREE — the
  model invented a plausible "opinion" for JARVIS out of the error text
  itself.
- **Fixed**: `_judge()` now recognizes the four placeholder shapes
  `_ask_jarvis()` can return and skips the LLM judgment entirely,
  returning `aligned: None` with an honest "couldn't compare" note.
  `server.py`'s `_cmd_cross_check` now has a third branch for that case
  instead of folding it into "we don't agree."

### FAIL — goals and medicine tracking lost data on a container restart
- `services/friday_goals.py` and `services/friday_medicine.py` only ever
  wrote to a local JSON file, with no Turso mirror — the exact bug class
  already fixed for Spotify/Gmail/Calendar tokens in the prior session,
  never applied here.
- Confirmed live: the goal added in Round 1 ("Read 12 books this year")
  and the medicine added and logged as taken ("vitamin d") were both
  **completely gone** later in this same test session — no redeploy
  involved, just the process restarting (most likely the OOM
  restart from Round 1's #26 crash). `init_default_goals()` silently
  re-seeded the three starting goals because `get_active_goals()` came
  back empty, so the loss produced no error, just quietly wrong data.
- **Fixed**: both now mirror to Turso via the same `kv_get`/`kv_set`
  pattern already used for tokens.

### FAIL — `remember this` leaked raw, truncated JSON as the "summary"
```
"Stored: {\"insights\":[\"User has an anniversary on June 3rd\",\"User explicitly requests the system"
```
- `services/second_brain.py`'s `ingest()` asks the model for JSON, and
  when parsing that JSON failed (usually a `max_tokens` cutoff mid-object)
  it fell back to using the broken JSON text itself, truncated to 200
  chars, as the "summary" — surfaced straight to the boss.
- **Fixed**: falls back to an empty summary instead (`_cmd_remember_this`
  already reads that as a plain "Stored, boss.").

### FAIL — an empty LLM response falsely promised a follow-up
```
"Give me a second, boss."
```
- `core/friday_brain.py`'s `_clean()` turned any empty completion into
  this line, which reads as "still working on it" — but nothing was in
  flight and there's no retry mechanism; nothing was ever coming.
  Confirmed live on `_cmd_travel` ("im traveling to tokyo next week" got
  this instead of a travel brief).
- **Fixed**: now says "Didn't get anything back there, boss — try that
  again?" — honest about what happened.

### SAFETY FINDING (fixed, not live-reproduced) — `emergency contact` trigger was dangerously broad
- `CAPABILITY_MAP["emergency contact"]` (`core/friday_capabilities.py`)
  fires a **real** critical Pushover alert and speaks "Emergency services
  contacted" for any message containing the substring "emergency
  contact" — including totally mundane ones ("who's my emergency
  contact", "update my emergency contact info"). No confirmation gate.
  Not live-tested (would have sent a real alert to the boss's phone).
- **Fixed**: renamed the trigger to `"emergency contact protocol"`, a
  phrase nobody would type by accident, matching the specificity of every
  other key in this map (`"barn door protocol"`, `"deploy veronica"`,
  etc.). The capability itself is unchanged and still fully reachable.

## Passes

| Prompt | Handler | Result |
|---|---|---|
| `whats the weather` | weather | `"Boardman, Oregon, US: ☁️ +80°F"` — real data |
| `whats in the news today` | news | Honest "No news to report" |
| `translate hello to spanish` | translate | `"hola"` |
| `review this code: def add(a,b): return a+b` | code_review | `"Boss, Python. Add type hints."` |
| `people brief on jane` | people_brief | Honest "No intel on jane yet" |
| `who is calling from 555-1234` | caller_id | Honest "unknown caller, recommend skipping" |
| `i worked out today` | habit_log | `"Logged Exercise, boss. 1-day streak."` |
| `run diagnostics` | diagnostics | Honest system status (mac bridge not configured, etc.) |
| `diagnose yourself` | self_repair | Correctly started a real background test run (see note below) |
| `create a file called notes.txt: hello world` | create_file | Clean, content preserved |
| `open the file called notes.txt` | file_recall | Correctly recalled the same content |
| `turn off lights` | homekit | Honest "Not authorized — trust score isn't there" |
| `open notes` | mac_app | Same honest gate |
| `turn on the tv` | ha_toggle | Honest "Home Assistant isn't reachable" |

## Note: self-repair found a test failure it couldn't localize

`diagnose yourself` correctly started FRIDAY's own background test-suite
run (this is a real feature — see `core/self_repair.py`). Polling it back
reported:

> "Found a failing test but couldn't trace it back to one of my watched
> files — needs a human look." (`status: cannot_localize`)

The actual failing test name/traceback wasn't retrievable after that —
`_run_state` is in-process memory only and gets cleared once reported, and
re-running the full suite live again risked another OOM given Round 1's
findings, so this wasn't chased further. The local suite (829 tests, same
code) is fully green with everything unconfigured (`tests/conftest.py`
deliberately clears all credentials for local runs). The most likely
explanation is a test that behaves differently with the live deploy's
real configured services (Turso, Gmail, etc.) than in the cleared-credential
local environment — worth a follow-up session with real credentials
available locally to reproduce and localize it properly.

## Fixes applied

All FAILs above fixed with tests in `tests/test_second_wave_fixes.py` (15
new tests). Full suite: 829 tests pass.
