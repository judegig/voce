# study.md — learning reference for Voce

This file exists so that whenever you want to *learn* something from this
codebase (not just get a feature built), there's a standing map of what the
program does, why it's built the way it is, and which parts are worth
studying as general programming technique. Treat it as a table of contents
into the real teacher — the source files themselves, which carry the "why"
in their comments.

Update this file when the architecture changes meaningfully (new module,
new pipeline stage, a rewritten subsystem) — not on every small edit.

> ### 🎯 Prepping for an interview? Go straight to [§8, the Question Bank](#8-the-question-bank).
>
> That's the study plan. Sections 1-6 are a codebase map, §7 is how the
> drilling works, §9-10 are backup depth. **§8 is what actually gets
> asked** — worked top-down, Tier 1 first, each answer sized to be
> delivered and then finished.
>
> The governing rule, because it's the easiest one to lose: **answer
> short, land the specific number or mechanism, then stop.** Depth is held
> in reserve for a follow-up, not spent up front.

---

## 1. What the program does, in one paragraph

Voce is a system-wide, hotkey-driven dictation tool. Hold a hotkey anywhere
on the OS, speak, release. It transcribes the audio (locally via
whisper.cpp, or via the Groq/OpenAI Whisper API), runs the raw transcript
through a small LLM cleanup pass (removes filler words, fixes punctuation),
and pastes the result at the cursor via the clipboard — then restores
whatever was on the clipboard before.

## 2. The end-to-end data flow

```
hotkey down  ──▶  Recorder.start()          (audio.py)
                     │  seeds the recording with the ring-buffer preroll
hotkey up    ──▶  Recorder.stop(tail=0.35s) (audio.py)
                     │  writes a temp 16-bit PCM WAV, or None if silent
                     ▼
                transcribe(audio_path, settings)   (transcribe.py)
                     │  local whisper.cpp subprocess, or Groq/OpenAI HTTP call
                     ▼
                clean_transcript(text, settings)   (cleanup.py)
                     │  Claude Haiku strips filler words, fixes punctuation
                     ▼
                paste_text(cleaned)                (paste.py)
                     │  clipboard save → copy → Ctrl/Cmd+V → clipboard restore
```

Every stage after "hotkey up" degrades gracefully instead of blocking
dictation entirely:
- Silent recordings are dropped before any engine sees them (`audio.py`).
- A transcription failure just logs and aborts that one utterance
  (`app.py::_process`).
- A cleanup failure, or no `ANTHROPIC_API_KEY`, falls back to the raw
  transcript rather than raising (`cleanup.py`).

That "never let an optional stage break the required path" pattern is
worth internalizing — it shows up three separate times in this codebase.

## 3. Module map

| File | Owns | Study it for |
|---|---|---|
| [app.py](src/voce/app.py) | Wires every other module together; owns the Tk mainloop | Coordinating threads with a single-threaded GUI event loop |
| [audio.py](src/voce/audio.py) | Mic capture, ring-buffer preroll, WAV writing | Continuous audio streaming, device negotiation, silence detection |
| [hotkey.py](src/voce/hotkey.py) | Global hold/toggle hotkey listener + interactive capture | State machines over async key events, debouncing |
| [transcribe.py](src/voce/transcribe.py) | Local subprocess + two HTTP-API speech-to-text backends | Swappable-backend design, subprocess vs. API tradeoffs |
| [cleanup.py](src/voce/cleanup.py) | LLM post-processing of the raw transcript | Prompt injection defense, graceful LLM-call fallback |
| [paste.py](src/voce/paste.py) | Clipboard save/paste/restore, simulated keystrokes | Why "just simulate a paste" has sharp edges |
| [overlay.py](src/voce/overlay.py) | The floating "Listening..." pill | Tk `Toplevel` windows, `after()`-based timers instead of threads |
| [tray.py](src/voce/tray.py) | System tray icon + menu | Native-menu quirks (`pystray`), polling vs. push for external state |
| [config.py](src/voce/config.py) | `settings.json` + `.env` loading, typed dataclasses | Defensive parsing of hand-editable config |
| [autostart.py](src/voce/autostart.py) | Launch-at-login registration | Per-OS system integration (registry / launchd / XDG autostart) |
| [languages.py](src/voce/languages.py) | Whisper language code → display name table | Curated subsets vs. full API surface |

## 4. Concepts worth studying, with where to see them

### 4.1 Concurrency: three threads that must not block each other
Voce runs on (at least) three concurrent contexts, and the design is
shaped almost entirely by keeping them from stepping on each other:

- **The Tk mainloop thread** — owns all GUI state (`overlay.py`'s pill).
  Anything touching Tk from another thread must be marshaled in via
  `self._root.after(0, fn)` (see `app.py::_on_hotkey_down`).
- **The pynput listener thread** — delivers key events. It must never
  block, so `_on_hotkey_up` (`app.py`) hands off the actual audio-stop work
  (which *sleeps* for the capture tail) to a fresh daemon thread rather
  than doing it inline.
- **The pystray icon thread** — runs the native tray menu's event loop.

Study `app.py::_finish_recording` and the comment above `_on_hotkey_up` for
a concrete example of "why can't I just call this function directly" in a
multi-threaded GUI app.

### 4.2 The ring-buffer preroll trick (`audio.py`)
The mic stream is kept open *continuously*, not opened on keypress. A
`collections.deque` holds the last `preroll_seconds` of audio at all times;
when recording starts, that buffer is prepended to the new recording. This
solves a real, measured problem: people start talking as they press the
key, not after, and losing 150ms off the front measurably corrupts
transcription ("What are you saying" → "body shape"). The same trick runs
in reverse at the tail end (`CAPTURE_TAIL_SECONDS` in `app.py`) — the mic
keeps recording briefly *after* the key is released.

This is a generalizable pattern for any "capture the moment it started
before you knew it started" problem (motion-triggered cameras, crash
dumps, etc.): keep a small rolling buffer live at all times instead of
starting capture on the trigger.

### 4.3 Defensive parsing of hand-editable config (`config.py`)
`settings.json` is meant to be hand-edited by users per the README. Every
value pulled from it goes through `dict.get(key, default)` with a
dataclass default, and structurally invalid values (e.g. a bad
`hotkey_mode`) fall back to the default with a printed warning instead of
raising. A malformed JSON file doesn't crash the app either — `load_settings`
catches the parse error and runs on defaults for that session. This is the
general shape of "config that trusts the user to make mistakes without
punishing them for it."

### 4.4 Prompt-injection defense in the cleanup pass (`cleanup.py`)
The raw transcript is untrusted text that gets fed to an LLM — and a
dictated question ("how are you doing") is textually indistinguishable
from a real message to the model. `cleanup.py` handles this with two
layers:
1. **Tagging as data**: the transcript is wrapped in `<transcript>...</transcript>`
   with an explicit system-prompt instruction that its contents are never
   addressed to the model.
2. **Defensive output stripping**: `_strip_tag()` removes the wrapper if
   the model echoes it back, because trusting the instruction alone isn't
   enough — a leaked `<transcript>` in the pasted text would be worse than
   the original problem.

This is a small, self-contained case study in prompt injection risk and
mitigation that generalizes to any "wrap untrusted user text and hand it
to an LLM" system (search, summarization, RAG, etc.).

### 4.5 Platform quirks handled explicitly, not abstracted away
Rather than hiding OS differences behind a fake unified API, the code
calls them out and handles each concretely:
- **WASAPI device multiplication** (`audio.py::list_input_devices`) —
  Windows surfaces the same physical mic 3-4 times across host APIs
  (MME/DirectSound/WASAPI/WDM-KS); the fix is filtering to one host API,
  not a generic dedup heuristic.
- **Per-device sample rate negotiation** (`audio.py::_resolve_sample_rate`)
  — WASAPI shared mode only accepts a device's native rate, so the
  recorder probes candidate rates instead of hardcoding one.
- **pystray's `__code__.co_argcount` menu-action inspection**
  (`tray.py::_make_device_action`) — pystray rejects a lambda with default
  args because it introspects the callable's *declared* arg count, not
  its bindable one. The workaround is a plain closure factory. This is a
  good example of "read the library's actual validation logic before
  assuming Python idioms will work with it."
- **`pynput` global hooks look like a keylogger to AV/EDR** (README
  Permissions section) — same primitive, different intent; worth knowing
  this pattern (global key hook = keylogger signature) shows up in any
  cross-platform hotkey library.

### 4.6 Two hotkey modes as one small state machine (`hotkey.py`)
`HoldToTalkHotkey` tracks two booleans — `_active` (is the full combo
currently physically held) and `_recording` (toggle-mode only: is a
recording logically open) — and derives start/stop events from press/
release deltas against a *set* of required keys, not from individual key
identity. Worth studying `_on_press`/`_on_release` as a minimal example of
turning raw, unordered key events into a clean start/stop signal, including
the debounce reasoning (key-repeat must not double-fire a toggle).

### 4.7 Interactive input capture reusing the same primitive twice
`capture_hotkey()` (`hotkey.py`) opens a *second*, temporary `pynput`
listener to let the user press a new hotkey combo from the tray menu — and
explicitly stops the normal listener first so the two don't race over the
same key events. It has its own timeout (15s) so a user who clicks "Change
Hotkey..." and walks away doesn't leave the app in a state with no working
hotkey at all. This "borrow the same low-level primitive for a one-shot
interactive capture, with a bounded timeout as the escape hatch" pattern is
reusable anywhere you need "press any key to configure X."

### 4.8 Silence/hallucination handling (`audio.py`)
Whisper-family models have no "there is no speech" output token — fed
near-silent audio, they hallucinate a plausible-sounding phrase from
training data (almost always "Thank you.", traceable to YouTube outro
data). `SILENCE_PEAK_AMPLITUDE` discards recordings whose peak int16
amplitude never clears a threshold, *before* any engine sees them —
solving the problem once for all three transcription backends rather than
per-engine. Good example of pushing a fix to the earliest point in the
pipeline where it covers every downstream branch.

### 4.9 Clipboard-based paste, and its known ceiling
`paste.py` doesn't type text character-by-character; it copies to the
clipboard, simulates Ctrl/Cmd+V, then restores the previous clipboard
contents. Fast and works in virtually any app, but it's fundamentally
lossy: `pyperclip` only round-trips *text*, so a clipboard that held an
image or file selection before dictation loses that content permanently.
Worth noting when evaluating "just use the clipboard" as a general
input-injection strategy — it's simple and robust for text, but not
content-type-preserving.

## 5. Design decisions and their tradeoffs (from the README)

| Decision | Why | Cost |
|---|---|---|
| Mic stream stays open continuously | Enables the preroll buffer (§4.2) | OS shows mic as "in use" at all times; disable via `preroll_seconds: 0` |
| Three swappable transcription engines | Offline-first by default, cloud as opt-in speed/cost tradeoff | Local requires a manual whisper.cpp build + model download |
| Cleanup pass is optional and silently skippable | Dictation must work with zero cloud dependency | Raw transcript (with filler words) pastes if no API key is set |
| No accounts, no telemetry, no update mechanism | Minimal, single-purpose tool by design | No crash reporting, no usage analytics to debug field issues from |

## 6. Where to go deeper

- Read the README's **Troubleshooting** section — each entry documents a
  real bug that was diagnosed and fixed, including what was *ruled out*
  along the way (e.g. the "last word cut off" entry lists mic startup
  latency and resampling as confirmed non-causes). That's a good model for
  writing bug postmortems that save the next person from re-treading dead
  ends.
- Read `README.md`'s **Configuration** table alongside `config.py`'s
  dataclasses side by side — it's a clean example of keeping user-facing
  docs and the typed schema they describe in sync.

---

## 7. Interview Prep

> ## ▶ START HERE NEXT SESSION
>
> **The plan changed on 2026-08-15. Read this before teaching anything.**
>
> The old plan was "learn every module in depth, bottom-up." That was the
> wrong shape for the actual goal. Sessions so far went deep on Module 1
> audio internals — `dtype`, ring-buffer mechanics, sample arithmetic —
> which is **Tier 3** material an interviewer reaches only if they read
> the source. Meanwhile the **Tier 1 questions that get asked in every
> single interview have never been drilled once**:
>
> - "Walk me through this project." ← guaranteed, never practiced
> - "Walk me through what happens when you press the hotkey."
> - "What was the hardest bug you hit?" ← taught, never delivered aloud
>
> **New plan: drill §8's question bank top-down, Tier 1 first.** Depth is
> earned by tier, not by module order. Do not start a new Module 1 topic
> until Tier 1 is ✅.
>
> **Resume at: Q1 (the 60-second pitch).** Ask it cold, grade the answer
> against §8's "Say this," then Q2, then Q3.
>
> **Still-open questions, now correctly prioritized:**
> 1. **(Tier 1 — war story)** In **hold** mode instead of toggle, the
>    self-paste bug produced a *different* symptom. `paste_text` presses
>    Ctrl then releases it — what would a hold-mode user have
>    experienced? *Do this one; it's the Tier 1 follow-up.*
> 2. **(Tier 3 — but keep as a drill)** `preroll_seconds = 0.3`,
>    `CAPTURE_TAIL_SECONDS = 0.35`, 16kHz. Hold the hotkey exactly 1
>    second — how many samples reach whisper.cpp? *Low-tier topic, but
>    it's the isolated drill for the 🔴 top weakness (never landing the
>    final number), which damages answers at **every** tier. Keep it.*
> 3. **(Tier 3)** [audio.py:126-130](src/voce/audio.py#L126-L130) uses
>    `_active_rate`, not `sample_rate`. What breaks if it used
>    `sample_rate`, and on which machines would you notice?

This is the interview track: being able to **defend Voce out loud, at the
right length**, not to recite it exhaustively.

### The core discipline: answer short, then stop

The goal is a tight answer that invites the follow-up *they* choose —
not a monologue that burns the clock and buries the good part.

Every question in §8 has two parts, and the split is the whole point:

| Part | Length | Rule |
|---|---|---|
| **Say this** | 20–60 seconds | The complete answer. Deliver it, then **stop talking.** |
| **Only if probed** | as needed | Held in reserve. Never volunteered. |

**Short does not mean vague.** These two failure modes are opposites and
both lose points:

- ❌ *Too long* — reciting the "only if probed" depth unasked. Wastes the
  interview, and the strongest point gets lost in the middle.
- ❌ *Too vague* — "it changes the recording," trailing off before the
  number. This is the documented 🔴 top weakness below.

A good answer is **short and specific**: it lands the concrete figure or
mechanism, then ends. If a number belongs in the answer, the short
version still has to say it — brevity is never an excuse to drop it.

### Teaching format (how every question gets drilled)

For each question in §8, in this order:

1. **Ask it cold**, exactly as an interviewer would phrase it. No warm-up
   and no teaching first — the point is to find out what comes out under
   pressure, not to confirm a lesson just given.
2. **Grade the answer** by the §8 stance below, against the "Say this"
   text *and* against the real code.
3. **Grade the length too** — an answer that's correct but 3× too long is
   marked ⚠️, not ✅. Say which part should have been cut and which part
   should have been held for "only if probed."
4. **Re-teach only the gap**, then re-ask. Don't re-teach what landed.

**When a concept genuinely isn't understood** (not just badly delivered),
fall back to the two-layer format that has reliably worked:

- **Layer 1 — simple analogy**, built from physical reality upward. Never
  entered mid-way (see the learner profile: that fails outright).
- **Layer 2 — technical explanation** in the actual code, at
  interview-defensible depth. Concept first, *then* code as its own
  separate pass — never folded together.

But this is now the **fallback**, not the default. The default is: ask,
grade, patch the gap. Teaching from scratch is for topics that are
genuinely new or genuinely broken.

**Code must always be linked, never just pasted.** Any time code is shown
— in a lesson, a correction, or a question — it has to point at the real
location in this repo as a clickable link
([file.py:12-20](src/voce/file.py#L12-L20)), so the code can be opened and
read in context rather than judged from an isolated snippet. A bare code
block with no link is not acceptable, even for a one-line example. For
hypothetical modifications ("what if this line said X instead"), link the
real line first, then describe the change against it.

### Status markers

- ⬜ **Not drilled** — never asked.
- 🟡 **Shaky** — answered once with gaps, or taught but never delivered
  aloud. See the note for what's missing.
- ⚠️ **Right but too long** — content correct, length wrong. Re-deliver
  inside the time budget before it counts.
- ✅ **Interview-ready** — correct, complete, *and* delivered at the right
  length. Held up under at least one follow-up.

A ✅ flips back to 🟡 if a later follow-up exposes a gap. Mastery means it
survived a probe, not that the first pass sounded fluent.

### Grading stance: blunt, never agreeable

The goal is competence under interview pressure, not comfort. Praise that
isn't earned is actively harmful here — it converts a gap into a blind
spot, and the interviewer finds it instead.

**Rules for grading every explain-back:**

1. **Analyze before responding.** Check the claim against the actual code
   in this repo first. Never accept an answer because it sounds confident,
   is phrased fluently, or is *close* to right.
2. **Verdict first, explicitly stated.** Every answer gets labelled:
   **correct**, **partially correct**, or **wrong**. No burying the
   verdict under hedging or a compliment sandwich.
3. **Partially correct is the most important verdict** — and the one most
   likely to be fudged into "yes, basically." Never do that. State
   precisely which part is right, which part is wrong, and *why* the wrong
   part is wrong. A half-right answer given a full pass is worse than an
   answer marked wrong, because it silently locks in the error.
4. **Congratulate only on genuinely correct and complete answers.** When
   it's right, say so plainly and move on — no inflation, no padding.
5. **Never soften a correction to preserve momentum.** If something is
   wrong, say "this is wrong" and rebuild it. Do not lead with what was
   right in order to cushion it.
6. **Push back on confidently-stated errors hardest.** Fluent, assured
   delivery of a wrong answer is the most dangerous case — that's exactly
   what gets carried into an interview unchallenged.
7. **Flag every slip, even trivial ones** — wrong numbers, wrong function
   names, wrong direction of a relationship — even when the surrounding
   reasoning is clearly sound. Interviewers grade what was *said*.
8. **Don't accept vague answers as correct.** "It changes the recording"
   is not an answer. Demand the specific mechanism and the concrete
   consequence before marking anything ✅.
9. **Grade length as strictly as content.** A correct answer delivered at
   3× the budget is ⚠️, not ✅ — say explicitly which sentences should
   have been cut and which belonged in "only if probed." Rambling past
   the answer is a real interview failure, not a harmless surplus: it
   burns time and buries the strongest point mid-monologue.
10. **But never let brevity excuse vagueness.** Trimming is cutting
    *padding*, not cutting the number, the mechanism, or the concrete
    consequence. If the short version drops the figure, that's not a
    tight answer — it's the top weakness wearing a disguise.

Being disagreeable is the job here. An answer marked ✅ in the progress
table must mean it would survive a real interviewer's follow-up — not that
it was good enough to move on from.

### Learner profile — read this before teaching

A living record of observed learning patterns, updated every session.
The point is to stop re-running teaching approaches that have already
failed, and to lead with the ones that have already worked.

**Recurring failure mode: collapsing two adjacent concepts into one.**
This is the single most consistent error pattern, seen twice in one
session:
- Merged *capture* with *detection* — assumed the sampling stage decides
  whether someone is speaking (it doesn't; that's a separate later stage).
- Merged *`samplerate`* with *`dtype`* — read a dtype change as a change
  in measurements-per-second.

→ **Countermeasure:** whenever two things live near each other in the code
(adjacent lines, same function call, similar names), pre-emptively split
them with a side-by-side diagram *before* teaching either one. Don't wait
for the confusion to surface. Explicitly name what each one is **not**.

**Analogies must be built from the ground up, not entered mid-way.**
Confirmed repeatedly: explanations that start at the target concept fail
outright ("you're starting from the middle of the topic"). Explanations
that start at physical reality and build upward land immediately.
- ❌ Failed: buckets of water drops; height in cm vs. metres. Both mapped
  arbitrarily onto the concept with no physical throughline.
- ✅ Worked: sound as a wobbling drum skin → measuring its position →
  a list of numbers. Door swing measured in notches vs. percent open.
- ✅ **Best of all — their own:** sample rate as a **video refresh rate /
  frames per second**. Reuse this one; it was self-generated and stuck
  instantly.

→ **Countermeasure:** always start Layer 1 at something physical and
already-known, and walk up to the concept in visible steps. If an analogy
requires a mapping that has to be *asserted* rather than *felt*, it will
fail — discard it and rebuild.

**Numeric precision slips in verbal explain-backs.** Three occurrences in
one session, all on the same figure: "16 times per second" (×2) and
"60,000 times per second" (×1), each time meaning **16,000**. Reasoning
around the number is consistently sound; the spoken figure is what slips.
Since explain-backs are dictated (stream-of-consciousness, self-corrections
embedded), spoken numbers are the weak point — and an interviewer *will*
hear the wrong figure as the real answer.

→ **Countermeasure:** flag every numeric slip immediately, even when the
underlying understanding is clearly correct. Interview stakes are on the
spoken number, not the intent.

**🔴 TOP WEAKNESS — stops one step short of the final arithmetic.** Three
occurrences, unbroken:
1. "8,000 per second" — never produced × 3s = 24,000.
2. "three seconds into 16,000, so that's how much they hold" — never
   produced 48,000.
3. (earlier) 3s × 16,000 — left unstated entirely.

The reasoning is correct every time; the number is never spoken. This is
**not** a comprehension gap — it's a delivery habit, and it's the single
most interview-damaging pattern on this list, because a pause where a
number belongs reads as inability rather than as reasoning-in-progress.

→ **Countermeasure:** demand the closing number on every quantitative
question, and call out the omission explicitly each time even when the
mechanism is perfect. Prefer questions that *require* a landed figure.
Consider drilling this in isolation until it breaks.

**Answers the primary consequence but not the full set.** On the
`preroll_seconds` 0.3 → 3.0 question, correctly identified transcript
pollution from pre-press audio, but missed the **latency** cost (3 extra
seconds of audio to transcribe on every single utterance) — which is the
consequence an interviewer actually probes, since it's the reason the
value isn't simply set higher "to be safe."

→ **Countermeasure:** after a correct first consequence, always ask "what
else?" before grading. Prompt specifically for the performance/latency
axis and the user-visible axis, which are both consistently under-reported
relative to the correctness axis.

**Honest "I don't know" reports are reliable — and sometimes indict the
teaching.** Said plainly that they didn't know what [audio.py:306](src/voce/audio.py#L306)
did. Correct: it had been *referenced* in four separate questions without
ever being taught.

→ **Countermeasure:** never build a diagnostic question on code that
hasn't been explicitly taught yet. Audit question dependencies before
asking.

**Answers stop at the code boundary when asked about user impact.** Asked
what the *user experiences* when the silence threshold is raised, gave the
internal mechanism ("it discards the recording") instead of the symptom
(nothing appears, no error shown, works intermittently). Reasoning about
the code is solid; translating it into observable product behaviour is
not yet automatic.

→ **Countermeasure:** when the question is about user-visible behaviour,
don't accept a mechanism as the answer. Push for: what appears on screen,
what error is shown (often: none), and whether the failure is consistent
or intermittent. Intermittency in particular is never volunteered.

**Second-guesses correct technical vocabulary into vaguer words.** Used
"amplitude" correctly, then retracted it to "measurement" — despite the
constant being named `SILENCE_PEAK_AMPLITUDE`. Separately used
"appending" for what is actually **prepending**.

→ **Countermeasure:** when a correct technical term is used and then
abandoned, say so explicitly. Retreating from precise vocabulary reads as
uncertainty about one's own code in an interview. Same for opposite-word
slips (append/prepend, push/pop) — the concept can be right while the word
inverts the meaning.

**Concept lands before code — reliably, and in that order.** Grasps the
*why* of a mechanism from a good analogy, then needs the implementation
taught as a separate, explicit pass. Self-reports the gap accurately ("I
understood the topic but not the coding thing").

→ **Countermeasure:** never fold the code walkthrough into the concept
explanation as a supporting detail. Teach concept → confirm → *then* do
code as its own step. Code explanations must be **traced with concrete
values** (show the container's actual contents changing chunk by chunk),
not described in terms of data-structure names and complexity classes.
Naming `deque`/O(1)/`popleft` without first showing the thing filling and
draining does not land.

**Strong metacognition — self-corrects mid-sentence.** Has caught their
own drift while explaining ("wait, that's the mistake I did"). This is a
genuine asset: it means partial understanding is usually announced rather
than hidden, so gaps surface fast.

→ **Countermeasure:** trust the self-flags. When they say they don't
understand something, that report is accurate — rebuild rather than
rephrase.

**Reaches for plausible general knowledge when specifics are missing.**
Guessed audio ranges as 0..1 (the normalized convention seen everywhere
online) rather than the -32,768..32,767 this code actually uses.

→ **Countermeasure:** when a concept has a "textbook default" that differs
from what this repo does, teach the difference explicitly and say which
one their code uses. The generic answer will otherwise win by default.

**Wants everything anchored to the real repo.** Explicitly asked for
clickable code links rather than isolated snippets. Learning is grounded
in *this* codebase, not in abstract examples.

**Preferred pacing.** One concept per message. Walls of text stall
progress — this was raised directly at the start and reconfirmed by the
failure of the first dense Module 1 explanation.

### Known corrections to the original syllabus

Two assumptions in the original 4-module plan don't match the actual
codebase — flagged here so they never get rehearsed as fact in an
interview:

| Assumed | Actual (per code) |
|---|---|
| Audio buffered as float32 | `sounddevice` records `int16` PCM ([audio.py](src/voce/audio.py)); conversion to float32 happens inside the whisper.cpp binary, not in Python |
| Python loads whisper.cpp as a shared DLL via `ctypes` FFI | [transcribe.py](src/voce/transcribe.py)`::_transcribe_local` shells out to a compiled `whisper-cli` **binary via `subprocess.run`** — no FFI, no shared memory pointers, just a CLI call with a temp WAV in and a temp `.txt` out |
| Text injection via `ctypes` `SendInput` + active-window detection | [paste.py](src/voce/paste.py) copies to the clipboard, simulates Ctrl/Cmd+V via `pynput.keyboard.Controller`, then restores the previous clipboard — no active-window detection, no raw `SendInput` calls |

---

## 8. The Question Bank

**This is the study plan now.** Work top-down. Tier 1 is guaranteed to
come up and is worth more than all of Tier 3 combined; Tier 3 only gets
asked if the interviewer actually opens the source.

Each answer has a **Say this** (deliver it, then stop) and an **Only if
probed** (held in reserve). Delivering the reserve unasked is the mistake
this whole plan exists to fix.

> ⚠️ Before answering anything, check §7's *Known corrections* table.
> Three plausible-sounding claims about this codebase are **false** (FFI,
> float32 buffers, `SendInput`). Saying one confidently is worse than
> admitting you don't remember.

---

### 🔴 Tier 1 — Guaranteed. Drill these first.

#### Q1. "Tell me about this project." / "Walk me through Voce."

**Say this** (~45s):

> Voce is a push-to-talk dictation tool for Windows. You hold a hotkey
> anywhere in the OS, speak, release — and cleaned-up text appears at your
> cursor, in whatever app you're in.
>
> It's a five-stage pipeline: a global keyboard hook triggers mic capture,
> the audio goes to Whisper — either a local whisper.cpp binary or the Groq
> API — the raw transcript goes through Claude Haiku to strip filler words
> and fix punctuation, and then it pastes via the clipboard. It lives in
> the system tray, no window.
>
> The interesting engineering is in the audio capture and the threading —
> there are three event loops that can't block each other, and the capture
> has a couple of non-obvious tricks that came out of real transcription
> failures.

Then **stop**. That last sentence is bait — let them pick which thread to pull.

**Only if probed:** offline-first as a design goal, no accounts/telemetry,
three swappable engines, the tray menu's live device/language switching.

---

#### Q2. "Walk me through what happens when you press the hotkey."

**Say this** (~60s) — name the thread at each hop, that's what they're testing:

> The `pynput` listener thread sees the key and calls `Recorder.start()`.
> That doesn't open the mic — the mic is *already* streaming, so `start()`
> just flips a flag and seeds the recording with the pre-roll buffer.
>
> On release, that same listener thread does two things and nothing else:
> it marshals the overlay hide onto the Tk thread via `root.after`, and it
> spawns a daemon thread for the teardown. It can't do the teardown inline,
> because `Recorder.stop()` **sleeps** for the 0.35-second capture tail,
> and blocking the listener thread stalls every key event behind it.
>
> On that daemon thread: stop the capture, drop it if it's under 0.3
> seconds or below the silence threshold, write a temp WAV, transcribe,
> run the cleanup pass, paste, delete the temp file.

**Only if probed:** the exact drop conditions
([app.py:136-145](src/voce/app.py#L136-L145)), that transcription failure
logs and aborts just that utterance, that the paste is wrapped in
`suppressed()` (→ Q3), the `_maybe_flash_language` stale-result guard.

---

#### Q3. "What's the hardest bug you've hit?" / "A time you were wrong."

⭐ **The single highest-value answer in this codebase.** It has a real
user-visible symptom, a *wrong* first hypothesis, a correct root cause,
and verification. Interviewers reward the discarded hypothesis more than
the fix — so make sure the wrong turn actually gets said out loud.

**Say this** (~60s):

> The app pastes by simulating a real Ctrl+V. My hotkey was Ctrl. A global
> keyboard hook can't tell a synthetic keystroke from a human one — so the
> app's own paste re-triggered its own hotkey.
>
> In toggle mode that meant every paste immediately started a phantom
> recording, which **inverted the state**. So every tap after that did the
> opposite of what the user wanted. That's why it was hard: it presented as
> "the hotkey randomly stops working," not as a paste bug.
>
> My first fix was wrong. I assumed a dropped key-up event and added a
> debounce. It didn't help, and I reverted it. The actual fix is a
> `suppressed()` context manager that mutes the listener while the app is
> sending its own keystrokes.

**Only if probed:**
- **Why `finally` clears `_pressed` and `_active`**
  ([hotkey.py:135-142](src/voce/hotkey.py#L135-L142)) — events are
  *dropped, not tracked* while suppressed, so a key genuinely released
  during that window would linger as a phantom held key forever.
- **The tradeoff, worth volunteering:** suppression is scope-based, not
  identity-based — a real keypress in that ~100ms window gets swallowed
  too. The "proper" fix is the Windows `LLKHF_INJECTED` hook flag, which
  `pynput` doesn't expose and isn't cross-platform.
- **Defense in depth:** the `key in self._keys` guard
  ([hotkey.py:155-159](src/voce/hotkey.py#L155-L159)) — only a combo key
  can complete the combo.
- **Scope:** only affects Ctrl-based hotkeys. With `f9` there's no collision.

---

### 🟠 Tier 2 — Very likely. The "why did you build it that way" probes.

#### Q4. "Why is the microphone always on? That seems wasteful."

**Say this** (~30s):

> Because people start talking *as* they press the key, not after it. If
> you open the mic on keypress you've already lost the first syllable, and
> no amount of speed fixes that — the audio has to already exist when the
> key goes down.
>
> So the stream runs continuously and a ring buffer holds the last 0.3
> seconds, which gets prepended on keypress. I measured this: cutting
> 150ms off the front turned "What are you saying" into "body shape."

**Only if probed:** 4,800 samples ≈ **9.6 KB** of memory, negligible; the
real cost is the OS showing the mic as permanently in use (documented
tradeoff, `preroll_seconds: 0` disables it); nothing leaves memory outside
a recording; `stop()` clears the buffer so one dictation's tail can't leak
into the next.

---

#### Q5. "Why paste via the clipboard instead of typing the text out?"

**Say this** (~25s):

> Speed and compatibility. Simulating a few hundred keystrokes is slow and
> breaks on anything with input handling — autocomplete, editors that
> reformat as you type. A clipboard paste is one event and works in
> basically every app.
>
> The cost is that it's destructive to the clipboard, so I save and restore
> it around the paste. And that restore is lossy: `pyperclip` only
> round-trips text, so an image or file selection on the clipboard is gone.

**Only if probed:** the 50ms settle delays either side
([paste.py:29](src/voce/paste.py#L29), [36](src/voce/paste.py#L36)) —
the OS needs a moment to register the new clipboard contents; a native
`NSPasteboard`/Win32 implementation could preserve every type, which is
what a platform-specific build would do.

---

#### Q6. "Why shell out to a whisper.cpp binary instead of using bindings?"

⚠️ **Do not say FFI or `ctypes`.** It's `subprocess.run` on a CLI binary
([transcribe.py:86-88](src/voce/transcribe.py#L86-L88)) — temp WAV in,
temp `.txt` out.

**Say this** (~30s):

> It's a `subprocess` call — I write a temp WAV, run `whisper-cli` on it
> with a 120-second timeout, and read the text file it produces.
>
> I chose that over bindings because the process boundary buys isolation
> for free: whisper.cpp is native code, and if it crashes or hangs on a
> bad input it takes down a subprocess, not my app. I get a timeout and a
> non-zero exit code instead of a segfault in my process.
>
> The cost is process startup and going through the filesystem on every
> utterance — that's real, but it's small next to inference time.

**Only if probed:** parsing auto-detected language out of stderr with a
regex ([transcribe.py:108](src/voce/transcribe.py#L108)) and that this is
explicitly *not* a stable CLI contract — it falls back to `"auto"` rather
than raising; the `.en.bin` model warning
([transcribe.py:62-71](src/voce/transcribe.py#L62-L71)).

---

#### Q7. "Why run an LLM over the transcript? Isn't Whisper's output fine?"

**Say this** (~30s):

> Whisper transcribes what you *said*, including "um," false starts, and
> repeated words. That's correct as transcription but wrong as dictation —
> you want what you *meant* to write. So a Claude Haiku pass strips fillers
> and fixes punctuation and casing.
>
> Haiku specifically because this is latency-sensitive — it sits directly
> between the user finishing a sentence and text appearing.
>
> And it's strictly optional: no API key or cleanup disabled means the raw
> transcript pastes instead. A cleanup failure never breaks dictation.

**Only if probed** — this is where the **prompt injection** answer lives,
and it's a strong one:

> A dictated question is textually identical to a real question addressed
> to the model. Dictating "how are you doing" made it paste "Great!"
>
> Two layers of fix: the transcript is wrapped in `<transcript>` tags with
> a system prompt saying its contents are never addressed to the model, and
> then `_strip_tag()` defensively removes the wrapper if the model echoes
> it back — because pasting a literal `<transcript>` into the user's
> document would be worse than the original bug.

Also note: assistant prefill was deliberately **not** used — it 400s on
current Claude models.

---

#### Q8. "How do you handle concurrency here?"

**Say this** (~40s):

> Three contexts. The Tk mainloop owns all UI state, the `pynput` listener
> thread delivers key events, and `pystray` runs the tray menu's own loop.
> Plus a short-lived daemon thread per recording.
>
> Two rules hold it together. Anything touching the UI from another thread
> goes through `root.after(0, fn)` — Tk is single-threaded and calling into
> it directly from another thread corrupts it. And the listener thread
> never blocks: anything slow gets handed to a daemon thread.
>
> The audio callback has a third constraint — it runs on PortAudio's thread
> and holds the GIL, so it only does a copy and a deque append. Anything
> slower there and the sound card's buffer overruns.

**Only if probed:** `self._lock` guarding `_frames`/`_preroll`
([audio.py:116](src/voce/audio.py#L116)); the `_recording` flag needing no
lock because it's only touched from Tk-dispatched callbacks
([app.py:34-39](src/voce/app.py#L34-L39)); `_capture_lock` as a
non-blocking guard against two rival hotkey-capture threads.

---

#### Q9. "Why three transcription backends?"

**Say this** (~20s):

> Offline-first as the default, cloud as an opt-in tradeoff. Local
> whisper.cpp means it works with no network and nothing leaves the
> machine; Groq is faster and handles multiple languages without swapping
> model files. They're behind one `transcribe()` function returning a
> `TranscriptionResult`, so the rest of the pipeline doesn't know which ran.

**Only if probed:** local requires a manual build + model download (real
setup cost); the silence check lives at the *capture* stage so it protects
all three engines with one fix — that's the generalizable point.

---

### 🟡 Tier 3 — Only if they read the source. Don't volunteer these.

Short answers only. If you find yourself explaining int16 unprompted,
you've lost the thread.

| Question | Say this (1-2 sentences) |
|---|---|
| **Why `indata.copy()`?** | PortAudio reuses its buffer across callbacks. Without the copy, every frame in the list points at the same memory, and the recording comes out as the last 10-30ms block repeated. ([audio.py:118](src/voce/audio.py#L118)) |
| **Why `deque`, not a list?** | `popleft()` is O(1) on a deque, O(n) on a list. It runs on the audio callback thread — if that thread is slow, the sound card's buffer overruns and samples are lost permanently. |
| **What's the silence check?** | Whisper has no "no speech here" output — fed near-silence it hallucinates, almost always "Thank you." So recordings whose peak int16 amplitude never clears 500 get dropped before any engine sees them. ([audio.py:306](src/voce/audio.py#L306)) |
| **Why `np.abs()` first?** | Samples swing both directions; −30,000 is exactly as loud as +30,000. Without `abs()`, `.max()` only sees positive peaks. |
| **Why int16?** | It's what `sounddevice` gives you and what a WAV stores — range −32,768 to 32,767. Normalization to float32 happens *inside* whisper.cpp. Python never sees a float sample. ⚠️ Never claim float32 buffers. |
| **Why 16kHz?** | Whisper's encoder was trained on a log-mel spectrogram with a fixed FFT window tuned for 16,000 samples/sec — it's baked into the weights. But the rule applies at the *model* boundary, not the mic: WASAPI only accepts a device's native rate, so the recorder probes for one it'll take and the engine resamples. |
| **Why does the WAV use `_active_rate`?** | Because the stream may not have gotten the rate that was asked for. Tagging 48kHz audio as 16kHz makes it play — and transcribe — as slow, deep gibberish. ([audio.py:326](src/voce/audio.py#L326)) |
| **Why filter to WASAPI when listing devices?** | Windows surfaces the same physical mic once per host API — MME, DirectSound, WASAPI, WDM-KS — so one mic appears 3-4×. Filtering to one host API is the correct fix; a name-dedup heuristic isn't. |
| **What's the capture tail?** | Mirror image of pre-roll. People release the key on the final syllable, not after it — 300ms off the end turned "What are you saying" into "What are you?" So `stop()` keeps capturing 0.35s past the release. |

---

### 🟢 Tier 4 — Judgment questions. Often what actually separates candidates.

#### Q16. "How would you make this real-time / streaming?"

**Say this** (~40s):

> Right now it's deliberately whole-utterance batch — you get one clean
> transcript with full context, which is the right call for dictation
> because Whisper uses the whole clip to disambiguate.
>
> To stream it I'd chunk on a sliding window with overlap, run VAD to cut
> on natural pauses instead of fixed intervals, and reconcile overlapping
> hypotheses — the hard part is that later audio changes earlier words, so
> you need to either accept unstable text or hold a revision buffer.
>
> The bigger problem is the cleanup pass. It needs the full sentence to fix
> punctuation, so streaming would mean either dropping it or running it on
> stale partials. That's the real reason I didn't build it this way.

#### Q17. "How would you test this?"

**Say this** (~35s) — *be honest, this project has no test suite:*

> Honestly, it doesn't have one right now — it's been tested by use and by
> targeted manual experiments, like A/B-ing trimmed recordings to find the
> capture tail value.
>
> If I added tests: the pure logic is very testable — the hotkey state
> machine takes synthetic key events, the ring buffer takes fake arrays,
> `_strip_tag` is a pure function. I'd feed `Recorder` prerecorded WAV
> frames instead of a live device and assert on the silence threshold. The
> genuinely hard parts to test are the OS-level pieces — the global hook
> and the paste — which is exactly where the worst bug lived.

**Only if probed:** the self-paste bug *was* verified by simulated
reproduction, which is the closest thing to a regression test here.

#### Q18. "This installs a global keyboard hook. Isn't that a keylogger?"

**Say this** (~25s):

> Same primitive, different intent — and I'd rather name that than dodge
> it. It's a low-level hook that sees every key event; the difference is
> that it only compares against the configured combo and never stores or
> transmits anything. AV and EDR products do flag it, and that's
> documented in the README rather than hidden.
>
> The mic is the same shape of concern: it's always open, so I documented
> that explicitly and made it switchable off.

#### Q19. "What would you do differently?"

**Say this** (~30s) — *pick two real ones, don't list everything:*

> Two things. There's no test suite, and the parts I'd most want covered
> are the state machine and the pipeline — which are testable, I just
> didn't.
>
> And I'd reconsider the clipboard paste. It's the right 90% solution, but
> it's destructive to user state and the restore is text-only. A
> platform-specific implementation could preserve every clipboard type.
> That's a case where cross-platform convenience cost real fidelity.

#### Q20. "What's the latency, end to end?"

⚠️ **Don't invent a number.** Be precise about what's measured and what isn't.

**Say this** (~30s):

> I haven't instrumented it end to end, so I'll give you the parts I know.
> The fixed overhead I control is about 0.45 seconds — a 0.35-second
> capture tail plus two 50ms clipboard settle delays. Mic startup is 6-45ms
> and irrelevant since the stream's already open.
>
> The variable cost is the two model calls, and those dominate — Whisper
> plus the Haiku cleanup pass. If I were optimizing, that's where I'd
> measure first, and the obvious win is overlapping the cleanup request
> with the tail of transcription rather than running them strictly in
> series.

---

### Progress table

**Primary table — the question bank.** This is what determines readiness.

| # | Question | Tier | Status | Notes |
|---|---|---|---|---|
| Q1 | "Tell me about this project" | 🔴 1 | ⬜ Not drilled | **Never once practiced despite being guaranteed.** Start here |
| Q2 | "What happens when you press the hotkey?" | 🔴 1 | ⬜ Not drilled | Pipeline is understood in pieces; never delivered as one narrative |
| Q3 | "Hardest bug you've hit" | 🔴 1 | 🟡 Shaky | Content taught 2026-08-09 and understood, but **never said out loud**. Must include the *wrong* first hypothesis — that's the scoring part. Hold-mode follow-up still open |
| Q4 | "Why is the mic always on?" | 🟠 2 | 🟡 Shaky | Concept ✅ verified. Untested as a *timed* answer; risk here is over-explaining the ring buffer |
| Q5 | "Why clipboard instead of typing?" | 🟠 2 | ⬜ Not drilled | |
| Q6 | "Why subprocess, not bindings?" | 🟠 2 | ⬜ Not drilled | ⚠️ Guard against the FFI misconception |
| Q7 | "Why an LLM cleanup pass?" | 🟠 2 | ⬜ Not drilled | Prompt-injection follow-up is a strong answer — make sure it's ready |
| Q8 | "How do you handle concurrency?" | 🟠 2 | ⬜ Not drilled | GIL/audio-callback point was taught; never assembled into an answer |
| Q9 | "Why three backends?" | 🟠 2 | ⬜ Not drilled | |
| Q10-15 | Tier 3 code probes (table above) | 🟡 3 | partial | Most content ✅/🟡 in the module table below; none rehearsed *as short answers* |
| Q16 | "How would you make it real-time?" | 🟢 4 | ⬜ Not drilled | |
| Q17 | "How would you test this?" | 🟢 4 | ⬜ Not drilled | Requires admitting there's no suite — practice saying that without flinching |
| Q18 | "Isn't this a keylogger?" | 🟢 4 | ⬜ Not drilled | |
| Q19 | "What would you do differently?" | 🟢 4 | ⬜ Not drilled | |
| Q20 | "What's the latency?" | 🟢 4 | ⬜ Not drilled | ⚠️ Highest fabrication risk — end-to-end was never measured |

**Secondary table — depth topics.** Feeds the answers above. Do **not**
work through this top-to-bottom; pull from it only when a question in the
primary table exposes a gap. Rows marked ⬜ that no Tier 1-2 question
depends on are genuinely optional.

| Module | Topic | Status | Notes |
|---|---|---|---|
| 1 — Mic-to-Buffer | **Foundation:** what a sample is (vibration → drum position → list of numbers) | ✅ Verified | Nailed the key distinction on re-test: capture just collects numbers, it makes no speech/no-speech judgment. Also solid on sample rate ≈ "refresh rate" and number size = loudness. Winning analogy: **video frames per second** (their own) |
| 1 | Quantitative reasoning (3s × 16,000 = 48,000 samples) | ✅ Verified | Was unanswered on first pass, filled in during correction — worth restating out loud in interviews |
| 1 | 16kHz golden rule (why the rate matters to the model, not just the mic) | 🟡 Taught | Awaiting explain-back |
| 1 | numpy buffer dtype — `int16` (-32,768..32,767), **not** float32 / not 0..1 | 🟡 Retaught | First analogy (buckets/drops) failed. Retaught via **door notches vs. percentage open**. Triggered by the misconception that loud ≈ 1.0 — the 0..1 range is float32 *inside whisper.cpp*, never in Python. Ties to why `SILENCE_PEAK_AMPLITUDE = 500` not `0.015`. Explain-back pending |
| 1 | ⚠️ **`samplerate` vs `dtype` — two independent dials** | ✅ Verified | Was the session's biggest confusion (read a dtype change as changing measurements/sec). Fixed on re-test: correctly stated samplerate = how often it records, independent of dtype. The "16" collision is the trap — `samplerate=16000` = 16,000 measurements/sec ([audio.py:187](src/voce/audio.py#L187)); `dtype="int16"` = 16 **bits** per number ([audio.py:189](src/voce/audio.py#L189)); `float32` = 32 bits, NOT 32,000 measurements |
| 1 | Live-mod: `int16` → `float32` silently kills the app | 🟡 Taught | Peak can never exceed 1.0, threshold is 500 → every recording discarded as silence at [audio.py:306](src/voce/audio.py#L306), whisper.cpp never runs, no error shown. Threshold at [audio.py:20](src/voce/audio.py#L20) is expressed in int16 units and nothing revalidates it |
| 1 | Silence check — `np.abs(audio).max() < SILENCE_PEAK_AMPLITUDE` | 🟡 Partially verified | Taught late (had been *referenced* in 4 questions before ever being explained — teaching error, not a learner gap). Analogy: doorway height sensor, only the tallest reading matters. Key points: `abs()` because loud = big in *either* direction; exists because Whisper hallucinates "Thank you." on silence; placed at capture stage so it protects all 3 engines at once ([audio.py:301-314](src/voce/audio.py#L301-L314)). **Live-mod 500→5000 answered partially:** got the discard mechanism, missed all three user-facing consequences — silent failure with no error at all ([app.py:141-144](src/voce/app.py#L141-L144)), scale (normal speech peaks ~3,000-10,000, so it cuts ordinary speech not just quiet talkers), and intermittency (loud speech still works → unpredictable, hardest kind to debug). Re-test pending |
| 1 | **Contrast:** why dtype breaks the silence check but samplerate doesn't | 🟡 Taught | dtype changes the *size* of numbers (fatal); samplerate changes *how many* (harmless). Framed with their own analogy: 30fps vs 60fps doesn't change how bright the room is |
| 1 | numpy buffer *shape* — `(blocksize, 1)` per callback → `(total_samples, 1)` | ⬜ Not started | Split out from dtype; teach after dtype lands |
| 1 | Why `indata.copy()` in the callback (diagnostic question pending) | 🟡 Taught | Your answer pending |
| 1 | Ring-buffer preroll — **concept** | ✅ Verified | Explained back correctly and unprompted: mic always running, holds last 0.3s, glued onto the front on keypress, and *why* (people talk as they press). Vocabulary slip: said "appending" for what is **prepending** (front, not end) |
| 1 | Ring-buffer preroll — **code layer** | 🟡 Retaught | First attempt dumped `deque`/`popleft`/O(1) without building up — self-reported as not understood (accurate report). Retaught as a 5-step visual walkthrough: two containers → callback branch on `_capturing` → concrete fill/drop trace with real numbers → `_frames = list(_preroll)` handoff → why `deque` (O(1) `popleft` on the audio callback thread). Explain-back pending |
| 1 | Live-mod: `preroll_seconds` 0.3 → 3.0 | 🟡 Partially verified | Got transcript pollution (pre-press audio becomes part of the dictation) ✅. **Missed latency** — 3 extra seconds transcribed on every utterance, the real reason the value isn't set higher. Failed to land 48,000 samples / 96 KB. Also worth knowing: previous dictation's tail *can't* leak in, `stop()` clears `_preroll` ([audio.py:290-294](src/voce/audio.py#L290-L294)) |
| 1 | Capture tail on stop (`CAPTURE_TAIL_SECONDS`) | 🟡 Taught | Mirror image of pre-roll — pre-roll guards the *start*, tail guards the *end*. Explain-back pending |
| 1 | **Cost of always-on capture** (asked unprompted — good instinct) | 🟡 Taught | Compute is negligible: ~31 callbacks/sec, ~31 KB/s memcpy, 9.6 KB steady-state memory. Real costs are non-compute: permanent mic-in-use indicator (the documented tradeoff), battery/idle-state, and — the interview-grade point — **the GIL**: the callback is Python on PortAudio's audio thread, so a busy main thread delays it and the sound card's buffer overruns, losing samples permanently. That's *why* the callback holds only a copy + deque op. Alternative (open on keypress) costs 6–45ms startup **and** loses the leading audio |
| 1 | WASAPI device enumeration + sample-rate negotiation | ⬜ Not started | |
| 1 | Silence detection (`SILENCE_PEAK_AMPLITUDE`) | ⬜ Not started | |
| 2 — Subprocess Boundary (not FFI) | Correction: subprocess, not ctypes FFI | ⬜ Not started | |
| 2 | `subprocess.run` args, timeout, stdout/stderr handling | ⬜ Not started | |
| 2 | Passing data via temp files instead of memory pointers | ⬜ Not started | |
| 2 | Parsing whisper.cpp's stderr for auto-detected language | ⬜ Not started | |
| 2 | Groq/OpenAI HTTP alternative to the local subprocess path | ⬜ Not started | |
| 3 — Inference & Chunking | Latency vs. accuracy tradeoffs (model size, engine choice) | ⬜ Not started | |
| 3 | No real-time streaming/chunking — whole-utterance batch design | ⬜ Not started | |
| 3 | Silence/hallucination handling as a form of VAD | ⬜ Not started | |
| ⭐ **War story** | **Self-paste feedback loop** — app's own Ctrl+V retriggered its own hotkey | 🟡 Taught | Highest-value interview story in the codebase (real bug, wrong first hypothesis, root-caused, verified by simulation). Uncommitted as of 2026-08-09 |
| ⭐ | The `suppressed()` context manager ([hotkey.py:119-142](src/voce/hotkey.py#L119-L142)) | 🟡 Taught | Explain-back pending |
| ⭐ | Why `_pressed.clear()` / `_active = False` in the `finally` | 🟡 Taught | Explain-back pending |
| ⭐ | The `key in self._keys` guard ([hotkey.py:155-159](src/voce/hotkey.py#L155-L159)) | ⬜ Not started | **Omitted from the AI's own summary** — present in the diff but never explained. Classic interview trap: a line in your code you can't account for |
| 4 — Windows Text Injection | Correction: clipboard + simulated paste, not `SendInput` | ⬜ Not started | |
| 4 | Clipboard save/restore mechanics (`pyperclip`) | ⬜ Not started | |
| 4 | Simulated Ctrl+V via `pynput.keyboard.Controller` | ⬜ Not started | |
| 4 | Why there's no active-window detection, and what that implies | ⬜ Not started | |

Update both tables after every round. Flip 🟡 → ✅ only on an answer that
is correct, complete, **and** inside its time budget; use ⚠️ when the
content was right but the delivery ran long. On an incomplete answer, add
a one-line note on what was missing, re-teach just that gap, and re-ask
before flipping to ✅.

---

## 9. Revision sheet — 📋 cold-read before an interview

Condensed summary of all material taught through 2026-08-09. Facts and
defensible one-liners only; the full teaching write-ups are in §10.

> **This is backup depth, not the script.** The script is §8. Read this to
> refresh mechanisms you might get probed on — don't try to work it into
> answers unprompted.

---

#### A. Audio fundamentals

**What a sample is.** Sound = air pushing a drum skin in and out. The mic
measures its position over and over; each measurement is a **sample**.
Positive = pushed out, negative = caved in, zero = silence. A recording is
nothing but a long list of these numbers.

**Sample rate = how often you measure.** 16,000 times/second = 16kHz.
Best analogy: **video frames per second**. More per second = more detail.

**Capture makes no judgment.** The recorder faithfully records silence
just as diligently as speech. Whether anyone actually spoke is decided
*later*, in a separate stage. Do not conflate capture with detection.

**The two independent dials** — both in
[audio.py:186-192](src/voce/audio.py#L186-L192), and the #1 source of
confusion because both contain "16":

| Line | Setting | Meaning |
|---|---|---|
| [187](src/voce/audio.py#L187) | `samplerate=16000` | **How often** — 16,000 measurements per second |
| [189](src/voce/audio.py#L189) | `dtype="int16"` | **What kind of number** — 16 **bits** each |

`float32` = 32 **bits**, *not* 32,000 measurements.

**int16 range: −32,768 to +32,767.** Whole numbers, raw amplitude.
Silence ≈ 0. Normal speech peaks ≈ 3,000–10,000. A shout ≈ 25,000.
**Not 0..1** — that's the float32 range Whisper uses internally, produced
by dividing by 32,768 *inside whisper.cpp*. Python never sees a float32
audio sample.

**The 16kHz golden rule.** Whisper's encoder was trained on a log-mel
spectrogram with a fixed FFT window/hop tuned for 16,000 samples/sec —
baked into the weights, not a runtime setting. But
[`_resolve_sample_rate`](src/voce/audio.py#L150-L182) does *not* force
16kHz at the mic: WASAPI shared mode only accepts a device's native rate,
so it probes candidates and records at whatever the device accepts.
Resampling to 16kHz happens inside whisper.cpp / the cloud APIs. **The
rule applies at the model boundary, not the microphone boundary.**

---

#### B. The silence check — [audio.py:306](src/voce/audio.py#L306)

```
np.abs(audio).max() < SILENCE_PEAK_AMPLITUDE   # threshold = 500
```

- **Analogy:** a doorway height sensor — you don't read all 10,000
  entries, you ask "what was the tallest reading all day?" One number
  answers it.
- **Why `abs()` first:** samples swing both ways; `-30000` is exactly as
  loud as `+30000`. Without it, `.max()` only finds positive-going peaks
  and misses half of every waveform.
- **Why it exists:** Whisper models have no "there is no speech here"
  output. Fed near-silence they hallucinate — almost always *"Thank
  you."*, because so much training data is YouTube outros.
- **Where it sits:** at the capture stage
  ([audio.py:301-314](src/voce/audio.py#L301-L314)), so it protects **all
  three** transcription backends at once instead of needing three fixes.

---

#### C. Pre-roll ring buffer

**Concept.** The mic runs *continuously*, holding the last 0.3 seconds.
On keypress, that already-captured audio is **prepended** (front, not
end) to the recording. People start talking *as* they press — losing
150ms off the front turned *"What are you saying"* into *"body shape"* in
real testing.

**Two containers:**

```
_preroll  (deque)  →  IDLE.      Size-capped. Oldest chunks dropped.
_frames   (list)   →  RECORDING. Unbounded until stop().
```

The callback ([audio.py:115-124](src/voce/audio.py#L115-L124)) branches on
`self._capturing` and writes to exactly one.

**The ring, traced** (cap 4,800 samples; chunks of 1,000):

```
c1 → 1000   c2 → 2000   c3 → 3000   c4 → 4000    (under cap, keep all)
c5 → 5000 → OVER → drop oldest → 4000
c6 → 5000 → drop oldest → 4000     ... forever
```

New in the back, old falls out the front. Never grows.

**The handoff** ([audio.py:250-259](src/voce/audio.py#L250-L259)):
`_frames = list(_preroll)` — the recording starts *already holding* audio
from before the press.

**Why `deque` not `list`:** `popleft()` is O(1) on a deque, O(n) on a list
(every element shifts). This runs on the **audio callback thread** — if
that thread is slow, the sound card's buffer overflows and samples are
lost permanently.

**Memory cost:** 0.3s × 16,000 = 4,800 samples × 2 bytes ≈ **9.6 KB**.
Negligible.

---

#### D. Live-modification scenarios (interview gold)

| Change | What happens | Why |
|---|---|---|
| `dtype="int16"` → `"float32"` | 💀 **App silently dies entirely.** Nothing ever pastes, no error shown | Peak can never exceed 1.0; threshold is 500, so *every* clip is discarded as silence. The threshold at [audio.py:20](src/voce/audio.py#L20) is expressed in int16 units and nothing revalidates it |
| `samplerate` 16000 → 8000 | ✅ Silence check still works fine | Rate changes **how many** numbers, not their **size**. 30fps vs 60fps doesn't change how bright the room is. (3s → 24,000 samples) |
| `SILENCE_PEAK_AMPLITUDE` 500 → 5000 | Normal speech gets discarded. User sees **nothing at all** — no text, no error ([app.py:141-144](src/voce/app.py#L141-L144) bare-returns). **Fails intermittently** — loud speech still works | Normal speech peaks 3,000–10,000, so a 5,000 threshold cuts ordinary talking, not just quiet talking |
| `preroll_seconds` 0.3 → 3.0 | 48,000 samples (96 KB) buffered. Pre-press audio (other people, TV) pollutes the transcript **and** adds 3 seconds of audio to transcribe on *every* utterance | Latency is the real reason not to set it high "to be safe." Previous dictation's tail *can't* leak in — `stop()` clears `_preroll` ([audio.py:290-294](src/voce/audio.py#L290-L294)) |

---

#### E. The self-paste feedback loop (⭐ best interview story)

**The bug.** Voce listens for Ctrl to start recording, then **presses
Ctrl itself** to paste ([paste.py:31-34](src/voce/paste.py#L31-L34)). A
global listener can't distinguish a synthetic keystroke from a real one.

**Toggle-mode failure chain:**
```
tap → START        tap → STOP → paste sends Ctrl+V
                                  └─► listener sees Ctrl → START (phantom)
tap → "STOP" a recording the user never started
```
The phantom **inverts the state**, so it presents as *"the hotkey randomly
stops working"* — which is why the first fix (a debounce, on a
dropped-key-up theory) was wrong and got reverted.

**The fix, three parts:**
1. [hotkey.py:119-142](src/voce/hotkey.py#L119-L142) — `suppressed()`
   context manager; both handlers early-return while set.
2. [app.py:192-197](src/voce/app.py#L192-L197) — paste wrapped in it.
3. [hotkey.py:155-159](src/voce/hotkey.py#L155-L159) — `key in self._keys`
   guard, so only a combo key can complete the combo.

**Why the `finally` clears `_pressed` / `_active`:** events are *dropped,
not tracked* while suppressed. A real key released during the paste window
would never be seen, leaving a phantom held key forever.

**Tradeoff to volunteer:** suppression is scope-based, not
identity-based — real keypresses in that ~100ms window are swallowed too.
The "proper" fix (Windows `LLKHF_INJECTED` flag) isn't exposed by
`pynput` and isn't cross-platform.

**Only affects Ctrl-based hotkeys.** With `f9` there'd be no collision.

---

#### F. Corrections to the original syllabus — never rehearse these wrong

| Assumed | Actual |
|---|---|
| float32 buffers | `int16` — float conversion happens inside whisper.cpp |
| `ctypes` FFI into a whisper.cpp DLL | `subprocess.run` on a `whisper-cli` binary; temp WAV in, temp `.txt` out |
| `SendInput` + active-window detection | Clipboard + simulated Ctrl+V via `pynput`; no window detection at all |

---

---

## 10. Saved lesson notes

Full text of each topic as taught, in the two-layer format, kept here so
it can be reread without re-deriving it. A topic gets added here the first
time it's taught; it stays even after being marked ✅.

> **Deepest layer — reference only.** Nothing here should be recited in an
> interview at this length. It exists so a gap can be re-read rather than
> re-taught from scratch.

#### Module 1, Topics 1-2: The 16kHz golden rule + the numpy buffer shape

**Layer 1 — analogy.**

Sound is like a wiggly rope you're shaking up and down. To store it in a
computer, you take a snapshot of how high the rope is, many times every
second. Whisper (the AI) learned to understand speech by studying ropes
snapped exactly 16,000 times per second. Hand it a rope snapped a
different number of times per second, and it's like giving someone
directions in miles per hour when they only think in kilometers per
hour — the numbers don't mean what they expect until something converts
them.

Separately: your microphone hands you numbers like a whole-number height
measurement — "172" (centimeters) — simple and compact. The AI actually
prefers decimal measurements — "1.72" (meters) — for its math. Something
in the pipeline has to convert between the two formats; in Voce, that
conversion happens later, inside the whisper.cpp program, not in the
Python code that captures the audio.

**Layer 2 — technical.**

- **16kHz golden rule:** Whisper's encoder was trained on a log-mel
  spectrogram computed with a fixed FFT window/hop size tuned specifically
  for 16,000 samples/second — that framing is baked into the trained
  weights, not a runtime setting. Feed it audio at a different rate
  unconverted and every spectrogram frame represents a different slice of
  real time than the model expects.
  [audio.py:150-182](src/voce/audio.py#L150-L182) (`_resolve_sample_rate`)
  doesn't force 16kHz at the mic — WASAPI shared mode only accepts a
  device's native rate, so it probes candidates (the configured rate, the
  device's own default, then 48000/44100 as fallbacks) via
  `sd.check_input_settings` and records at whichever one the device
  actually accepts. The local whisper.cpp binary and the cloud APIs both
  resample to 16kHz internally at inference time — the "golden rule"
  applies at the model boundary, not the microphone boundary.
- **Buffer shape/dtype:** `sounddevice`'s `InputStream` is opened with
  `dtype="int16"`, `channels=1`. Each callback delivers `indata` as a
  numpy array of shape `(blocksize, 1)`, dtype `int16` (signed, -32768 to
  32767) — raw PCM amplitude, not normalized float. Frames accumulate in
  a Python list; `np.concatenate(frames, axis=0)` on stop merges them into
  shape `(total_samples, 1)`, still `int16`. That raw int16 array is
  written directly into a WAV file via Python's `wave` module
  (`sampwidth=2` bytes). Normalization to float32 in `[-1.0, 1.0]` happens
  only inside whisper.cpp when it reads that WAV file — never in Python.

#### ⭐ War story: the self-paste feedback loop (2026-08-09)

> **Note:** these changes were made in a separate AI-assisted session and
> were not originally understood by the author — they are being learned
> here after the fact. Verified present in the working tree via `git diff`
> before being written up. **Uncommitted** as of this entry.

**Layer 1 — analogy.**

You're counting how many people are in a room by listening for the door
click. Every click = one more person. But when *you* walk through the door
to check the count, the door clicks too — and you count yourself. Your
tally is now permanently off by one: you think there are 4 people inside
when there are 3, and every check from then on is wrong.

Voce did exactly this. It listens for the Ctrl key to know when the user
wants to record. Then it *presses Ctrl itself* to paste — and heard its
own keypress as the user's.

**Layer 2 — technical.**

The collision: [paste.py:31-34](src/voce/paste.py#L31-L34) sends a real
Ctrl+V through the OS via `pynput`'s `Controller`. The global listener in
[hotkey.py](src/voce/hotkey.py) is an OS-level hook — it sees *every* key
event, and nothing in what `pynput` surfaces distinguishes a synthetic
keystroke from a human one. With `hotkey = "ctrl_l"`, the paste's own Ctrl
press satisfied the combo.

The failure chain in **toggle** mode:

```
 tap ctrl  → START recording
 tap ctrl  → STOP  → transcribe → paste sends Ctrl+V
                                    └─► listener sees Ctrl → START (phantom!)
 tap ctrl  → "STOP" ... a recording the user never knowingly started
```

The phantom recording **inverts the state**, so every later tap does the
opposite of what the user intends — which presents as "the hotkey randomly
stops working," not as a paste bug. That misleading symptom is why the
first attempted fix (a debounce, on a dropped-key-up theory) was wrong and
had to be reverted.

**The fix, in three parts:**

1. **[hotkey.py:119-142](src/voce/hotkey.py#L119-L142)** — a `suppressed()`
   context manager sets `self._suppressed = True`; both
   [`_on_press`](src/voce/hotkey.py#L149-L150) and
   [`_on_release`](src/voce/hotkey.py#L176-L177) return immediately while
   it's set. A software mute, since the OS gives no "this was injected"
   signal through this library.
2. **[app.py:192-197](src/voce/app.py#L192-L197)** — the paste call is
   wrapped in `with self._hotkey.suppressed():`.
3. **[hotkey.py:155-159](src/voce/hotkey.py#L155-L159)** — a `key in
   self._keys` guard so only a key that's actually part of the combo can
   complete it. *(Defense in depth — and notably missing from the summary
   handed to the author.)*

**The subtle part — why the `finally` block clears state:**

While suppressed, key events are **dropped, not tracked**. So if a real
key is genuinely released during the paste window, that release is never
recorded, and `self._pressed` would keep believing it's still held — a
phantom stuck key that could block or misfire the combo forever after.
Clearing `_pressed` and `_active` on exit resets to a known-good state
instead of a guessed one.

**Known tradeoff worth volunteering in an interview:** suppression is
scope-based, not identity-based. A *real* keypress that lands during the
paste window is swallowed too. Accepted because the window is tiny
(~100ms, two `settle_delay` sleeps) and the alternative — reading the
Windows `LLKHF_INJECTED` low-level-hook flag — isn't exposed by `pynput`
and wouldn't be cross-platform.

**Why it's the best interview story here:** a real user-visible bug, a
first hypothesis that was *wrong* and got disproven, a correct root cause,
and verification by simulated reproduction rather than eyeballing it.
Interviewers reward the discarded hypothesis more than the fix.

#### Module 1, Topic 3: Why `indata.copy()` in the callback

**Layer 1 — analogy.**

Imagine a delivery worker who reuses the same box for every delivery. If
you just peek at the letter while it's still sitting in their box, and
then they take the box back to reuse for the next delivery, what you were
looking at changes too — you never actually had the letter, just a view
into their box. Copying the letter onto your own paper means it stays
yours no matter what they put in the box next.

**Layer 2 — technical.**

`sounddevice`/PortAudio reuses its internal buffer across callbacks for
performance — the memory backing `indata` gets overwritten on the very
next audio block. `self._frames.append(indata.copy())` forces a real,
independent allocation. Without `.copy()`, every entry in `self._frames`
would reference the *same* underlying buffer, so by the time `stop()`
concatenates them, every "frame" would actually hold whatever the *last*
callback wrote — the recording would come out as the final ~10-30ms block
repeated over and over, not the full utterance.
