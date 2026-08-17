# study.md — interview prep for Voce

**The plan: [§3, the Question Bank](#3-the-question-bank).** Work it
top-down, Tier 1 first. Everything else in this file supports it.

The governing rule, because it's the easiest one to lose: **answer short,
land the specific number or mechanism, then stop.** Depth is held in
reserve for a follow-up, not spent up front.

| Section | What it's for |
|---|---|
| [§1](#1-the-codebase-in-one-page) | The codebase in one page — refresh the map |
| [§2](#2-how-the-drilling-works) | How drilling works + what's already known about how you learn |
| [§3](#3-the-question-bank) | **The questions and the answers. This is the plan.** |
| [§4](#4-progress) | What's ready and what isn't |
| [§5](#5-live-modification-drills) | Backup depth for "what if you changed X" probes |

---

## 1. The codebase in one page

> ### ⚙️ What's actually running on this machine (as of 2026-08-15)
>
> The code supports four stages. **This install runs three** — worth
> knowing before you describe it to anyone.
>
> | Stage | Status here |
> |---|---|
> | Capture | ✅ |
> | Transcribe — Groq `whisper-large-v3` | ✅ `GROQ_API_KEY` set |
> | Clean up — Claude Haiku | ❌ **skipped**, `ANTHROPIC_API_KEY` is empty |
> | Paste | ✅ |
>
> Cleanup bails at [cleanup.py:62-64](src/voce/cleanup.py#L62-L64) before
> any API call — silently, by design, so dictation survives with no cloud
> dependency. The pasted text is therefore the **raw** Whisper transcript.
>
> **It doesn't look broken, and that's the point.** `whisper-large-v3`
> already punctuates, capitalizes, *and* strips most filler words by itself
> — it was trained largely on subtitles, which omit disfluencies. So the
> output reads clean and the missing stage is genuinely hard to notice.
> (Confirmed by observation, then verified: feeding `clean_transcript` a
> filler-stuffed string returns it byte-identical.)
>
> Don't claim "um and uh survive into the paste" — they mostly don't.
> Whisper handles them.

Voce is a system-wide, hotkey-driven dictation tool. Hold a hotkey
anywhere on the OS, speak, release. It transcribes the audio (locally via
whisper.cpp, or via the Groq/OpenAI Whisper API), runs the raw transcript
through an LLM cleanup pass, and pastes the result at the cursor via the
clipboard — then restores whatever was on the clipboard before.

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

**Worth having ready as a theme:** every stage after "hotkey up" degrades
instead of blocking dictation. Silent recordings are dropped before any
engine sees them; a transcription failure logs and aborts that one
utterance; a cleanup failure or missing API key falls back to the raw
transcript. "Never let an optional stage break the required path" shows up
three separate times — that's a design principle you can name, not just
three coincidences.

| File | Owns |
|---|---|
| [app.py](src/voce/app.py) | Wires everything together; owns the Tk mainloop |
| [audio.py](src/voce/audio.py) | Mic capture, ring-buffer preroll, silence gate, WAV writing |
| [hotkey.py](src/voce/hotkey.py) | Global hold/toggle listener + interactive capture |
| [transcribe.py](src/voce/transcribe.py) | Local subprocess + two HTTP speech-to-text backends |
| [cleanup.py](src/voce/cleanup.py) | LLM post-processing of the raw transcript |
| [paste.py](src/voce/paste.py) | Clipboard save/paste/restore, simulated keystrokes |
| [overlay.py](src/voce/overlay.py) | The floating "Listening..." pill |
| [tray.py](src/voce/tray.py) | System tray icon + menu |
| [config.py](src/voce/config.py) | `settings.json` + `.env` loading, typed dataclasses |
| [autostart.py](src/voce/autostart.py) | Launch-at-login registration |
| [languages.py](src/voce/languages.py) | Whisper language code → display name table |

---

## 2. How the drilling works

### The core discipline: answer short, then stop

Every question in §3 has two parts, and the split is the whole point:

| Part | Length | Rule |
|---|---|---|
| **Say this** | 20–60 seconds | The complete answer. Deliver it, then **stop talking.** |
| **Only if probed** | as needed | Held in reserve. Never volunteered. |

**Short does not mean vague.** Two opposite failure modes, both lose points:

- ❌ *Too long* — reciting reserve depth unasked. Burns the clock and
  buries the strongest point mid-monologue.
- ❌ *Too vague* — "it changes the recording," trailing off before the
  number. This is the documented 🔴 top weakness below.

A good answer is **short and specific**: land the concrete figure or
mechanism, then end. Brevity is never an excuse to drop the number.

### Drill loop

1. **Ask it cold**, phrased as an interviewer would. No warm-up, no
   teaching first — the point is what comes out under pressure.
2. **Grade against the real code**, not against the "Say this" text alone.
3. **Grade the length too.** Correct but 3× too long is ⚠️, not ✅ — name
   which sentences to cut and which belonged in reserve.
4. **Re-teach only the gap**, then re-ask. Don't re-teach what landed.

**Fallback when a concept is genuinely not understood** (not just badly
delivered) — the two-layer format that has reliably worked:

- **Layer 1 — analogy**, built from physical reality upward, never entered
  mid-way.
- **Layer 2 — the real mechanism** in the actual code. Concept first,
  *then* code as its own separate pass — never folded together.

This is the fallback, not the default. Default is: ask, grade, patch.

**Code must always be linked, never just pasted** —
([file.py:12-20](src/voce/file.py#L12-L20)) so it can be read in context.
For hypothetical modifications, link the real line first, then describe
the change against it.

### Status markers

⬜ **Not drilled** · 🟡 **Shaky** (gaps, or taught but never said aloud) ·
⚠️ **Right but too long** · ✅ **Interview-ready** (correct, complete, in
budget, survived a follow-up)

A ✅ flips back to 🟡 if a later probe exposes a gap.

### Grading stance: blunt, never agreeable

Praise that isn't earned converts a gap into a blind spot, and the
interviewer finds it instead.

1. **Check the claim against the code first.** Never accept an answer
   because it's fluent, confident, or *close*.
2. **Verdict first, explicitly**: correct / partially correct / wrong. No
   compliment sandwich.
3. **"Partially correct" is the most important verdict** and the one most
   likely to get fudged into "yes, basically." State exactly which part is
   wrong and why. A half-right answer given a full pass is worse than one
   marked wrong — it silently locks in the error.
4. **Push hardest on confidently-stated errors.** Fluent delivery of a
   wrong answer is the most dangerous case.
5. **Flag every slip** — wrong numbers, wrong function names, inverted
   relationships — even when the surrounding reasoning is sound.
   Interviewers grade what was *said*.
6. **Don't accept vague as correct.** Demand the specific mechanism and
   the concrete consequence.
7. **Grade length as strictly as content** — but never let brevity excuse
   vagueness. Trimming cuts padding, not the number.

### Learner profile — read before teaching

Observed patterns. The point is to stop re-running approaches that already
failed and lead with ones that already worked.

| Pattern | Countermeasure |
|---|---|
| 🔴 **TOP WEAKNESS — stops one step short of the final arithmetic.** Three unbroken occurrences: "8,000 per second" (never × 3s = 24,000); "three seconds into 16,000" (never 48,000); 3s × 16,000 left unstated. Reasoning correct every time; the number never spoken. A pause where a number belongs reads as *inability*, not as thinking | Demand the closing number on every quantitative question. Call out the omission even when the mechanism is perfect. Prefer questions requiring a landed figure |
| **Collapses two adjacent concepts into one.** Merged *capture* with *detection*; merged *`samplerate`* with *`dtype`* | When two things live near each other in code, pre-emptively split them side-by-side *before* teaching either. Name what each one is **not** |
| **Numeric slips in spoken answers.** Said "16 times/sec" (×2) and "60,000 times/sec" (×1), all meaning **16,000** | Flag every numeric slip immediately. Interview stakes are on the spoken number, not the intent |
| **Answers the primary consequence, not the full set.** On `preroll_seconds` 0.3 → 3.0: got transcript pollution, missed the **latency** cost — the one an interviewer actually probes | After a correct first consequence, always ask "what else?" before grading. Prompt for the latency axis and the user-visible axis specifically |
| **Stops at the code boundary on user-impact questions.** Gave the mechanism ("it discards the recording") instead of the symptom (nothing appears, no error, works intermittently) | Push for: what's on screen, what error shows (often none), consistent or intermittent. Intermittency is never volunteered |
| **Retreats from correct technical vocabulary.** Used "amplitude" correctly then downgraded it to "measurement." Said "appending" for **prepending** | Say so explicitly when it happens. Retreating from precise words reads as uncertainty about your own code. Same for inverted pairs (append/prepend) |
| **Reaches for textbook defaults when specifics are missing.** Guessed audio range 0..1 (the normalized convention online) instead of the −32,768..32,767 this code uses | When a concept has a textbook default that differs from this repo, teach the difference explicitly and name which one your code uses |
| ✅ **Concept lands before code, reliably.** Gets the *why* from a good analogy, then needs implementation as a separate pass. Self-reports the gap accurately | Never fold the code walkthrough into the concept explanation. Trace code with **concrete values** — naming `deque`/O(1)/`popleft` without showing it fill and drain does not land |
| ✅ **Analogies must build from the ground up.** ❌ Failed: buckets of water; cm vs. metres. ✅ Worked: sound as a wobbling drum skin; door notches vs. percent open. ✅ **Best — their own: sample rate as video frames per second** | Start at something physical and already-known, walk up in visible steps. If a mapping must be *asserted* rather than *felt*, discard it |
| ✅ **Strong metacognition — self-corrects mid-sentence.** Catches their own drift ("wait, that's the mistake I did") | Trust the self-flags. "I don't know" is an accurate report — rebuild rather than rephrase |
| **Pacing.** One concept per message. Walls of text stall progress | Raised directly and reconfirmed by the failure of the first dense explanation |

### ⚠️ Known corrections — never rehearse these wrong

Three plausible-sounding claims about this codebase are **false**. Saying
one confidently is worse than admitting you don't remember.

| Sounds right | Actually |
|---|---|
| Audio buffered as float32 | `sounddevice` records **`int16`** PCM; float conversion happens inside whisper.cpp, never in Python |
| whisper.cpp loaded as a DLL via `ctypes` FFI | [`_transcribe_local`](src/voce/transcribe.py#L85) shells out to a **`whisper-cli` binary via `subprocess.run`** — temp WAV in, temp `.txt` out |
| Text injection via `SendInput` + active-window detection | [paste.py](src/voce/paste.py) uses **clipboard + simulated Ctrl+V** via `pynput`; no window detection at all |

---

## 3. The Question Bank

Work top-down. Tier 1 is guaranteed and worth more than all of Tier 3
combined; Tier 3 only comes up if the interviewer opens the source.

### 🔴 Tier 1 — Guaranteed. Drill these first.

#### Q1. "Tell me about this project." / "Walk me through Voce."

**Say this** (~45s):

> Voce is a push-to-talk dictation tool for Windows. You hold a hotkey
> anywhere in the OS, speak, release — and cleaned-up text appears at your
> cursor, in whatever app you're in.
>
> It's a four-stage pipeline — capture, transcribe, clean up, paste. A
> global keyboard hook starts a recording, the audio goes to Whisper —
> either a local whisper.cpp binary or a cloud API — the raw transcript
> goes through Claude Haiku to strip filler words and fix punctuation, and
> the result pastes via the clipboard. It lives in the system tray, no
> window.
>
> The interesting engineering is in the audio capture and the threading —
> there are three event loops that can't block each other, and the capture
> has a couple of non-obvious tricks that came out of real transcription
> failures.

Then **stop**. That last sentence is bait — let them pick the thread to pull.

**Only if probed:** offline-first as a design goal, no accounts/telemetry,
**three** swappable engines (`local`/`groq`/`openai`), a tap-to-toggle
alternative to hold-to-talk, live device/language switching from the tray.

⚠️ **Traps in this answer, all found by fact-checking a delivery:**
- Don't state a stage count you can't enumerate on demand. It's **four**;
  the hotkey is the trigger, not a stage.
- Don't say the hook "triggers mic capture" — the mic is *already*
  streaming. That contradicts your own Q4 answer two minutes later.
- Don't say "either local or Groq" — that asserts two engines. There are
  three.
- "For Windows" is the target, but it's cross-platform Python that also
  runs on Linux/X11. Don't claim a native Windows app.

---

#### Q2. "Walk me through what happens when you press the hotkey."

**Say this** (~60s) — name the thread at each hop, that's what's being tested:

> The `pynput` listener thread sees the key and calls `Recorder.start()`.
> That doesn't open the mic — the mic is *already* streaming, so `start()`
> just flips a flag and seeds the recording with the pre-roll buffer.
>
> On release, that same listener thread does two things and nothing else:
> marshals the overlay hide onto the Tk thread via `root.after`, and spawns
> a daemon thread for the teardown. It can't do the teardown inline,
> because `Recorder.stop()` **sleeps** for the 0.35-second capture tail,
> and blocking the listener thread stalls every key event behind it.
>
> On that daemon thread: stop the capture, drop it if it's under 0.3
> seconds or below the silence threshold, write a temp WAV, transcribe,
> run cleanup, paste, delete the temp file.

**Only if probed:** exact drop conditions
([app.py:140-149](src/voce/app.py#L140-L149)); transcription failure
aborts just that utterance; the paste is wrapped in `suppressed()` (→ Q3);
the `_maybe_flash_language` stale-result guard.

---

#### Q3. "What's the hardest bug you've hit?" / "A time you were wrong."

⭐ **The highest-value answer in this codebase.** Real user-visible
symptom, a *wrong* first hypothesis, correct root cause, verification.
Interviewers reward the discarded hypothesis more than the fix — so make
sure the wrong turn actually gets said out loud.

**Say this** (~60s):

> The app pastes by simulating a real Ctrl+V. My hotkey was Ctrl. A global
> keyboard hook can't tell a synthetic keystroke from a human one — so the
> app's own paste re-triggered its own hotkey.
>
> In toggle mode that meant every paste immediately started a phantom
> recording, which **inverted the state**. Every tap after that did the
> opposite of what the user wanted. That's why it was hard: it presented as
> "the hotkey randomly stops working," not as a paste bug.
>
> My first fix was wrong. I assumed a dropped key-up event and added a
> debounce. It didn't help, and I reverted it. The actual fix is a
> `suppressed()` context manager that mutes the listener while the app
> sends its own keystrokes.

The failure chain, if you need to draw it:

```
 tap ctrl  → START recording
 tap ctrl  → STOP → transcribe → paste sends Ctrl+V
                                   └─► listener sees Ctrl → START (phantom!)
 tap ctrl  → "STOP" ... a recording the user never knowingly started
```

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
- **Scope:** only affects Ctrl-based hotkeys. With `f9`, no collision.

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
> seconds, prepended on keypress. I measured this: cutting 150ms off the
> front turned "What are you saying" into "body shape."

**Only if probed:** 4,800 samples ≈ **9.6 KB**, negligible; the real cost
is the OS showing the mic permanently in use (documented, `preroll_seconds: 0`
disables it); nothing leaves memory outside a recording; `stop()` clears
the buffer so one dictation's tail can't leak into the next.

---

#### Q5. "Why paste via the clipboard instead of typing the text out?"

**Say this** (~25s):

> Speed and compatibility. Simulating a few hundred keystrokes is slow and
> breaks on anything with input handling — autocomplete, editors that
> reformat as you type. A clipboard paste is one event and works in
> basically every app.
>
> The cost is that it's destructive to the clipboard, so I save and restore
> around the paste. And that restore is lossy: `pyperclip` only round-trips
> text, so an image or file selection is gone.

**Only if probed:** the 50ms settle delays either side
([paste.py:29](src/voce/paste.py#L29), [36](src/voce/paste.py#L36)) — the
OS needs a moment to register the new clipboard; a native
`NSPasteboard`/Win32 implementation could preserve every type.

---

#### Q6. "Why shell out to a whisper.cpp binary instead of using bindings?"

⚠️ **Do not say FFI or `ctypes`.**

**Say this** (~30s):

> It's a `subprocess` call — I write a temp WAV, run `whisper-cli` on it
> with a 120-second timeout, and read the text file it produces.
>
> I chose that over bindings because the process boundary buys isolation
> for free: whisper.cpp is native code, and if it crashes or hangs on bad
> input it takes down a subprocess, not my app. I get a timeout and a
> non-zero exit code instead of a segfault in my process.
>
> The cost is process startup and going through the filesystem every
> utterance — real, but small next to inference time.

**Only if probed:** parsing auto-detected language out of stderr with a
regex ([transcribe.py:150](src/voce/transcribe.py#L150)), and that this is
explicitly *not* a stable CLI contract — it falls back to `"auto"` rather
than raising.

---

#### Q7. "Why run an LLM over the transcript? Isn't Whisper's output fine?"

**Say this** (~30s):

> The idea is that Whisper transcribes what you *said*, and dictation wants
> what you *meant to write* — so a Claude Haiku pass strips fillers and
> false starts. Haiku specifically because it's latency-sensitive, sitting
> between the user finishing a sentence and text appearing.
>
> Worth being honest though: it earns less than I expected.
> `whisper-large-v3` already punctuates, capitalizes, *and* drops most
> fillers on its own — it was trained on subtitles, which don't transcribe
> disfluencies. So against a modern Whisper the pass mostly buys
> *consistency* rather than transformation: guaranteed behavior instead of
> incidental, plus false starts and self-corrections, which Whisper does
> transcribe faithfully.
>
> And it's strictly optional — no API key and the raw transcript pastes
> instead. My own install runs Groq-only with no Anthropic key, and
> dictation works fine. That was the requirement.

💡 **Why this version scores better than "it strips filler words":** it
shows you measured your own assumption instead of trusting the design doc.
Claiming the pass fixes punctuation and fillers is the under-examined
answer — an interviewer who knows Whisper's behavior will catch it, and
"I found the newer model already did most of it" is a much stronger place
to be caught.

⚠️ **This was learned the hard way, 2026-08-15.** The written answer here
claimed Whisper leaves fillers in and cleanup removes them. Real usage
showed the opposite. Don't rehearse the old version.

**Only if probed** — the **prompt injection** answer lives here, and it's strong:

> A dictated question is textually identical to a real question addressed
> to the model. Dictating "how are you doing" made it paste "Great!"
>
> Two layers: the transcript is wrapped in `<transcript>` tags with a
> system prompt saying its contents are never addressed to the model, and
> `_strip_tag()` defensively removes the wrapper if the model echoes it
> back — pasting a literal `<transcript>` into the user's document would be
> worse than the original bug.

Also: assistant prefill was deliberately **not** used — it 400s on current
Claude models.

---

#### Q8. "How do you handle concurrency here?"

**Say this** (~40s):

> Three contexts. The Tk mainloop owns all UI state, the `pynput` listener
> thread delivers key events, `pystray` runs the tray menu's own loop. Plus
> a short-lived daemon thread per recording.
>
> Two rules hold it together. Anything touching the UI from another thread
> goes through `root.after(0, fn)` — Tk is single-threaded and calling into
> it directly from another thread corrupts it. And the listener thread
> never blocks: anything slow gets handed to a daemon thread.
>
> The audio callback has a third constraint — it runs on PortAudio's thread
> and holds the GIL, so it only does a copy and a deque append. Anything
> slower and the sound card's buffer overruns.

**Only if probed:** `self._lock` guarding `_frames`/`_preroll`
([audio.py:158](src/voce/audio.py#L158)); `_recording` needs no lock
because it's only touched from Tk-dispatched callbacks
([app.py:38-43](src/voce/app.py#L38-L43)); `_capture_lock` as a
non-blocking guard against two rival hotkey-capture threads.

---

#### Q9. "Why three transcription backends?"

**Say this** (~20s):

> Offline-first as the default, cloud as an opt-in tradeoff. Local
> whisper.cpp means no network and nothing leaves the machine; Groq is
> faster and handles multiple languages without swapping model files.
> They're behind one `transcribe()` returning a `TranscriptionResult`, so
> the rest of the pipeline doesn't know which ran.

**Only if probed:** local needs a manual build + model download; the
silence check lives at the *capture* stage so one fix protects all three
engines — that's the generalizable point.

---

### 🟡 Tier 3 — Only if they read the source. Don't volunteer these.

If you find yourself explaining int16 unprompted, you've lost the thread.

| Question | Say this (1-2 sentences) |
|---|---|
| **Why `indata.copy()`?** | PortAudio reuses its buffer across callbacks. Without the copy every frame points at the same memory, and the recording comes out as the last 10-30ms block repeated. ([audio.py:160](src/voce/audio.py#L160)) |
| **Why `deque`, not a list?** | `popleft()` is O(1) on a deque, O(n) on a list. It runs on the audio callback thread — if that's slow, the sound card's buffer overruns and samples are lost permanently. |
| **What's the silence check?** | Whisper has no "no speech here" output — fed near-silence it hallucinates, almost always "Thank you." So a recording is split into 30ms frames, the ones whose RMS clears a speech floor are totalled, and under 0.25s of that it's dropped before any engine sees it. ([audio.py:76-93](src/voce/audio.py#L76-L93), gate at [353](src/voce/audio.py#L353)) |
| **Why RMS over frames, not peak?** | The good version of this question. Peak was the first implementation and it *shipped the bug it existed to prevent*: peak is one sample, so a single transient clears it — and every recording ends with one, because releasing the hotkey is a key click into the mic. Speech isn't a spike, it's sustained energy, so measure how long it lasts. |
| **Why squash to float32 first?** | `frames * frames` on int16 overflows silently and the wrapped values read as *near-zero* energy — so the loudest frames would count as the quietest. Failure mode is inverted, not just wrong. |
| **Isn't a phrase blocklist a hack?** | It's the backstop, not the mechanism — the energy gate does the work. It only fires when the transcript is *entirely* a known stock phrase **and** the audio was already marginal, so a real "Thank you." survives. The honest tradeoff: it can't tell a hallucinated one from a genuine one on truly ambiguous audio, so the window is kept narrow enough to hold a single short word. |
| **Why int16?** | It's what `sounddevice` gives you and what a WAV stores — range −32,768 to 32,767. Normalization to float32 happens *inside* whisper.cpp; Python never sees a float sample. |
| **Why 16kHz?** | Whisper's encoder was trained on a log-mel spectrogram with a fixed FFT window tuned for 16,000 samples/sec — baked into the weights. But the rule applies at the *model* boundary, not the mic: WASAPI only accepts a device's native rate, so the recorder probes for one it'll take and the engine resamples. |
| **Why does the WAV use `_active_rate`?** | The stream may not have gotten the rate that was asked for. Tagging 48kHz audio as 16kHz makes it play — and transcribe — as slow, deep gibberish. ([audio.py:373](src/voce/audio.py#L373)) |
| **Why filter to WASAPI when listing devices?** | Windows surfaces the same mic once per host API — MME, DirectSound, WASAPI, WDM-KS — so one mic appears 3-4×. Filtering to one host API is the correct fix; a name-dedup heuristic isn't. |
| **What's the capture tail?** | Mirror image of pre-roll. People release the key on the final syllable, not after it — 300ms off the end turned "What are you saying" into "What are you?" So `stop()` keeps capturing 0.35s past the release. |

---

### 🟢 Tier 4 — Judgment. Often what separates candidates.

#### Q16. "How would you make this real-time / streaming?"

**Say this** (~40s):

> Right now it's deliberately whole-utterance batch — you get one clean
> transcript with full context, which is right for dictation because
> Whisper uses the whole clip to disambiguate.
>
> To stream it I'd chunk on a sliding window with overlap, run VAD to cut
> on natural pauses instead of fixed intervals, and reconcile overlapping
> hypotheses — the hard part is that later audio changes earlier words, so
> you either accept unstable text or hold a revision buffer.
>
> The bigger problem is the cleanup pass. It needs the full sentence to fix
> punctuation, so streaming means dropping it or running it on stale
> partials. That's the real reason I didn't build it this way.

#### Q17. "How would you test this?"

**Say this** (~35s) — *be honest, there's no test suite:*

> Honestly, it doesn't have one — it's been tested by use and by targeted
> manual experiments, like A/B-ing trimmed recordings to find the capture
> tail value.
>
> If I added tests: the pure logic is very testable — the hotkey state
> machine takes synthetic key events, the ring buffer takes fake arrays,
> `_strip_tag` and `is_silence_hallucination` are pure functions. The
> silence gate is the clearest case — `_voiced_seconds` takes a plain
> array, so synthetic room tone, room tone plus a key click, and real
> speech each pin down one row of a truth table without a mic. The
> genuinely hard parts are the OS-level pieces — the global hook and the
> paste — which is exactly where the worst bug lived.

**Only if probed:** the self-paste bug *was* verified by simulated
reproduction, the closest thing to a regression test here.

#### Q18. "This installs a global keyboard hook. Isn't that a keylogger?"

**Say this** (~25s):

> Same primitive, different intent — and I'd rather name that than dodge
> it. It's a low-level hook that sees every key event; the difference is it
> only compares against the configured combo and never stores or transmits
> anything. AV and EDR products do flag it, and that's documented in the
> README rather than hidden.
>
> The mic is the same shape of concern: always open, so I documented it
> explicitly and made it switchable off.

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

⚠️ **Don't invent a number.** Highest fabrication risk in the file.

**Say this** (~30s):

> I haven't instrumented it end to end, so I'll give you the parts I know.
> The fixed overhead I control is about 0.45 seconds — a 0.35-second
> capture tail plus two 50ms clipboard settle delays. Mic startup is 6-45ms
> and irrelevant since the stream's already open.
>
> The variable cost is the two model calls, and those dominate. If I were
> optimizing, that's where I'd measure first, and the obvious win is
> overlapping the cleanup request with the tail of transcription rather
> than running them strictly in series.

---

## 4. Progress

**Primary table — the question bank.** This determines readiness.

| # | Question | Tier | Status | Notes |
|---|---|---|---|---|
| Q1 | "Tell me about this project" | 🔴 1 | 🟡 Shaky | **2026-08-15: delivered as a recitation of the model answer, so it doesn't count as a pass.** Fact-checking it against the code did find 4 real defects (see the ⚠️ traps under Q1) — all in the *written* answer, now fixed. Re-ask cold, file closed |
| Q2 | "What happens when you press the hotkey?" | 🔴 1 | ⬜ Asked, unanswered | Asked cold 2026-08-15; answer pending. Understood in pieces; never delivered as one narrative |
| Q3 | "Hardest bug you've hit" | 🔴 1 | 🟡 Shaky | Content taught 2026-08-09 and understood, but **never said aloud**. Must include the *wrong* first hypothesis — that's the scoring part. Hold-mode follow-up still open |
| Q4 | "Why is the mic always on?" | 🟠 2 | 🟡 Shaky | Concept ✅ verified. Untested as a *timed* answer; risk is over-explaining the ring buffer |
| Q5 | "Why clipboard instead of typing?" | 🟠 2 | ⬜ Not drilled | |
| Q6 | "Why subprocess, not bindings?" | 🟠 2 | ⬜ Not drilled | ⚠️ Guard against the FFI misconception |
| Q7 | "Why an LLM cleanup pass?" | 🟠 2 | ⬜ Not drilled | Prompt-injection follow-up is strong — have it ready |
| Q8 | "How do you handle concurrency?" | 🟠 2 | ⬜ Not drilled | GIL/audio-callback point taught; never assembled into an answer |
| Q9 | "Why three backends?" | 🟠 2 | ⬜ Not drilled | |
| Tier 3 | Code probes (table above) | 🟡 3 | partial | Most content understood; none rehearsed *as short answers* |
| Q16 | "How would you make it real-time?" | 🟢 4 | ⬜ Not drilled | |
| Q17 | "How would you test this?" | 🟢 4 | ⬜ Not drilled | Requires admitting there's no suite — practice saying it without flinching |
| Q18 | "Isn't this a keylogger?" | 🟢 4 | ⬜ Not drilled | |
| Q19 | "What would you do differently?" | 🟢 4 | ⬜ Not drilled | |
| Q20 | "What's the latency?" | 🟢 4 | ⬜ Not drilled | ⚠️ End-to-end was never measured |

**Verified foundations** (carried over — don't re-teach these):

- ✅ What a sample is; capture makes no speech/no-speech judgment
- ✅ `samplerate` vs `dtype` as two independent dials (was the biggest
  confusion; fixed on re-test)
- ✅ 3s × 16,000 = 48,000 samples
- ✅ Ring-buffer preroll, concept level

**Still open:**

1. **(Tier 1 — do this one)** In **hold** mode instead of toggle, the
   self-paste bug produced a *different* symptom. `paste_text` presses
   Ctrl then releases it — what would a hold-mode user have experienced?
2. **(Drill for the 🔴 top weakness)** `preroll_seconds = 0.3`,
   `CAPTURE_TAIL_SECONDS = 0.35`, 16kHz. Hold the hotkey exactly 1 second
   — how many samples reach whisper.cpp? *Low-tier topic, but it's the
   isolated drill for never landing the final number, which damages
   answers at every tier.*
3. **(Tier 3)** [audio.py:168-172](src/voce/audio.py#L168-L172) uses
   `_active_rate`, not `sample_rate`. What breaks if it used
   `sample_rate`, and on which machines would you notice?

Update after every round. Flip 🟡 → ✅ only on an answer that is correct,
complete, **and** in budget; use ⚠️ when content was right but delivery
ran long.

---

## 5. Live-modification drills

"What happens if you change X" — a favourite probe because it tests
whether you understand the code or just memorized it. Backup depth; don't
volunteer.

| Change | What happens | Why |
|---|---|---|
| `dtype="int16"` → `"float32"` | 💀 **App silently dies entirely.** Nothing ever pastes, no error | RMS can never reach 1.0; the threshold is 180, so *no* frame is ever voiced and every clip is discarded as silence. `SPEECH_RMS_THRESHOLD` is in int16 units and nothing revalidates it |
| `samplerate` 16000 → 8000 | ✅ Silence check still fine | Rate changes **how many** numbers, not their **size**. 30fps vs 60fps doesn't change how bright the room is. Frame length is derived from the live rate, so frames stay 30ms either way |
| `SPEECH_RMS_THRESHOLD` 180 → 1800 | Normal speech discarded. User sees **nothing** — no text, no error ([app.py](src/voce/app.py) bare-returns) | Speech *frame RMS* runs several hundred to a few thousand, so 1,800 cuts ordinary talking, not just quiet talkers |
| Voiced-frame test → peak test | 🐛 **The original bug returns.** Silence + a key click transcribes as "Thank you." | Peak is decided by a single sample, so one transient clears it — and releasing the hotkey *is* a click into the mic. Speech is sustained energy; measure duration, not the loudest instant |
| `preroll_seconds` 0.3 → 3.0 | 48,000 samples (96 KB) buffered. Pre-press audio pollutes the transcript **and** adds 3 seconds to transcribe every utterance | Latency is the real reason not to set it high "to be safe." Previous dictation's tail can't leak in — `stop()` clears `_preroll` ([audio.py:335-341](src/voce/audio.py#L335-L341)) |

**The int16 range, since it anchors three of the above:** −32,768 to
+32,767. Silence ≈ 0, normal speech peaks ≈ 3,000–10,000, a shout ≈
25,000. **Not 0..1** — that's the float32 range *inside* whisper.cpp.
Peak and RMS are different measures of the same samples: RMS averages
energy over a window, so it runs several times lower than peak (idle room
tone ≈ 40, speech ≈ 1,000–5,000) and, unlike peak, a lone spike barely
moves it.

**The ring buffer, traced** (cap 4,800 samples, chunks of 1,000) — the
concrete-values version, since the abstract one didn't land:

```
c1 → 1000   c2 → 2000   c3 → 3000   c4 → 4000    (under cap, keep all)
c5 → 5000 → OVER → drop oldest → 4000
c6 → 5000 → drop oldest → 4000     ... forever
```

New in the back, old falls out the front. Never grows. On keypress,
`_frames = list(_preroll)` ([audio.py:292-301](src/voce/audio.py#L292-L301))
— the recording starts *already holding* audio from before the press.
