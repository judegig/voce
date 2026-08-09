# Voce

A lightweight, offline-first, system-wide dictation tool. Hold a hotkey anywhere
on your system, speak, release — Voce transcribes your speech, cleans it up
(removes filler words, fixes punctuation and casing), and pastes it at your
cursor.

- **No accounts.** Nothing to sign up for.
- **No telemetry.** Nothing is logged or sent anywhere except the API calls you
  explicitly opt into (see below).
- **Works fully offline** if you use the local whisper.cpp engine and disable
  LLM cleanup.

> **Platform note:** this build targets **Windows** (tested) using cross-platform
> Python libraries. It also runs on Linux (X11) and, with caveats, macOS — see
> [Platform notes](#platform-notes) below.

## How it works

1. Hold the configured hotkey (default: **Right Ctrl**).
2. A small "Listening..." pill appears near the top of your screen.
3. Speak. Release the hotkey when done.
4. Your speech is transcribed (locally via whisper.cpp, or via the Groq/OpenAI
   Whisper API — your choice) using whichever input device and language are
   currently selected in the tray menu.
5. The raw transcript is passed through an LLM (Claude Haiku 4.5 by default) to
   strip filler words and fix punctuation/casing.
6. The cleaned text is pasted at your current cursor position, and your
   previous clipboard contents are restored afterward.

The tray icon menu lets you:
- Toggle the whole thing on/off
- Pick the **input device** ("System Default" or a specific microphone/interface)
  — the list refreshes on its own within a couple seconds of plugging in or
  unplugging a mic, no app restart needed
- Pick a fixed **language**, or flip on **Auto-detect Language** to let the
  engine guess per recording (the detected language briefly flashes in the
  pill, and is printed to the console)
- Enable "launch at login"
- **Change Hotkey...** — click it, then press (and release) whatever key or
  key combo you want to use instead. The pill shows "Press new hotkey..."
  while it's listening. Press Esc to cancel without changing anything.
- **Tap to Start/Stop (instead of Hold)** — switches the hotkey from
  hold-to-talk to tap-to-toggle: tap the hotkey once to start recording,
  tap it again to stop. No need to hold anything down.

Device and language changes take effect on your *next* recording — no restart
needed, since both are read fresh from `settings.json` each time you hold the
hotkey.

---

## Installation

### 1. Requirements

- Python 3.10+
- A working microphone

### 2. Install dependencies

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Set up transcription

Voce supports three transcription engines, configured in `settings.json` ->
`transcription.engine`:

#### Option A — `"local"` (default, fully offline)

Requires building [whisper.cpp](https://github.com/ggerganov/whisper.cpp) and
downloading a model:

```powershell
git clone https://github.com/ggerganov/whisper.cpp
cd whisper.cpp
cmake -B build
cmake --build build --config Release
# Download a model (small ~500MB, or medium ~1.5GB for better accuracy):
python models/download-ggml-model.py small.en
cd ..
```

Then point `settings.json` at the built binary and model:

```json
{
  "transcription": {
    "engine": "local",
    "local": {
      "binary_path": "whisper.cpp/build/bin/whisper-cli.exe",
      "model_path": "whisper.cpp/models/ggml-small.en.bin"
    }
  }
}
```

(On Windows the binary is usually `build/bin/Release/whisper-cli.exe` —
adjust the path to wherever your build actually produced it.)

#### Option B — `"groq"` (cloud, fast, cheap)

Set `"transcription": {"engine": "groq"}` in `settings.json` and put your key
in `.env`:

```
GROQ_API_KEY=your-key-here
```

#### Option C — `"openai"` (cloud)

Set `"transcription": {"engine": "openai"}` and put your key in `.env`:

```
OPENAI_API_KEY=your-key-here
```

### 4. Set up cleanup (optional but recommended)

Copy `.env.example` to `.env` and add your Anthropic key:

```
ANTHROPIC_API_KEY=your-key-here
```

If this key is absent, or `cleanup.enabled` is `false` in `settings.json`,
Voce pastes the raw transcript unmodified — dictation still works, you just
skip the cleanup pass.

### 5. Run it

```powershell
python run.py
```

A tray icon should appear. Hold Right Ctrl, say something, and release.

---

## Configuration (`settings.json`)

| Key | Default | Meaning |
|---|---|---|
| `hotkey` | `"ctrl_r"` | The hotkey. A single [pynput key name](https://pynput.readthedocs.io/en/latest/keyboard.html#pynput.keyboard.Key) (e.g. `"f9"`, `"alt_r"`) or a `+`-joined combo (e.g. `"ctrl+alt"`). Normally set from the tray menu's **Change Hotkey...** item, which applies immediately, no restart needed. Editing this by hand still works too, but does require a restart. |
| `hotkey_mode` | `"hold"` | `"hold"` (hold the hotkey down to record, release to stop) or `"toggle"` (tap the hotkey to start, tap it again to stop). Normally set from the tray menu's **Tap to Start/Stop** checkbox, which applies immediately, no restart needed. |
| `sample_rate` | `16000` | Preferred microphone sample rate in Hz. Treated as a preference, not a demand: under Windows WASAPI a device only accepts its own native format, so if the selected mic rejects this rate Voce records at a rate the device *does* support and logs which one (some phone-as-mic and USB devices are 48kHz-only). The Groq/OpenAI engines resample server-side, so this costs nothing there. **`"local"` (whisper.cpp) requires 16kHz** — if your mic can't do 16kHz, use a cloud engine or a different mic. |
| `input_device` | `null` | Microphone/input device index, or `null` for the system default. Normally set from the tray menu's "Input Device" submenu, not edited by hand — takes effect on the next recording, no restart. |
| `preroll_seconds` | `0.3` | Seconds of audio buffered *before* you press the hotkey, prepended to the recording. People start speaking as they press rather than after, and losing even 150ms off the front wrecks the transcript (measured: "What are you saying" became "body shape"). **This keeps the mic stream open continuously**, so your OS will show the mic as in use whenever Voce is running — nothing is written to disk or sent anywhere outside an active recording, and idle audio lives only in a few hundred milliseconds of continuously-overwritten memory. Set to `0` to close the mic between recordings and accept the clipping. Restart required. |
| `transcription.engine` | `"local"` | `"local"`, `"groq"`, or `"openai"`. |
| `transcription.local.binary_path` | `whisper.cpp/build/bin/whisper-cli` | Path to the built whisper.cpp CLI binary. |
| `transcription.local.model_path` | `whisper.cpp/models/ggml-small.en.bin` | Path to the ggml model file. |
| `transcription.groq_model` | `"whisper-large-v3-turbo"` | Model name sent to the Groq API. |
| `transcription.openai_model` | `"whisper-1"` | Model name sent to the OpenAI API. |
| `transcription.language` | `"en"` | Language code used when `auto_detect_language` is `false`. Set from the tray menu's "Language" submenu (24 common languages); any Whisper language code works if you edit this by hand, even ones not in the tray list. Takes effect on the next recording. |
| `transcription.auto_detect_language` | `false` | When `true`, no fixed language is sent — the engine detects it per recording. Toggled from the tray menu. The detected language is printed to the console and briefly flashed in the pill. |
| `transcription.vocabulary_hints` | `[]` | List of names, project names, or jargon Whisper tends to mishear (e.g. `["Voce", "Groq", "judegig"]`), sent as a bias hint to the Groq/OpenAI API. It's a hint, not a strict allowlist — it nudges transcription toward these words, it doesn't force them. Only affects the `"groq"` and `"openai"` engines; the local whisper.cpp engine ignores it. Hand-edit only, restart required. |
| `cleanup.enabled` | `true` | Whether to run the LLM cleanup pass. |
| `cleanup.model` | `"claude-haiku-4-5"` | Any Claude model ID. Haiku 4.5 is the recommended default — it's fast and cheap, which matters for a latency-sensitive dictation pass. |
| `launch_at_login` | `false` | Kept in sync automatically when you toggle it from the tray menu. |

`input_device`, `transcription.language`, `transcription.auto_detect_language`,
`hotkey`, and `hotkey_mode` are normally changed from the tray menu (which
also writes them back to this file) and apply immediately, no restart.
Everything else requires editing `settings.json` directly and restarting
Voce.

---

## Permissions

### Windows

- **Microphone:** Windows will prompt for microphone access the first time
  Voce records, or you can pre-grant it under
  **Settings -> Privacy & security -> Microphone** -> enable "Let desktop apps
  access your microphone."
- **Global keyboard hook:** `pynput` installs a low-level keyboard hook to
  detect the hotkey system-wide. This does not require any special Windows
  permission, but some antivirus/EDR software flags global keyboard hooks as
  suspicious (they're the same primitive keyloggers use). If yours does,
  allow-list `python.exe` / your built `.exe` for this app.

### macOS

If you adapt/run this on macOS, `pynput`'s global listener needs two
permissions granted manually (System Settings -> Privacy & Security):

1. **Accessibility** — required for `pynput` to receive global key events at
   all.
2. **Input Monitoring** — required for `pynput` to *simulate* keystrokes
   (the Ctrl/Cmd+V paste).
3. **Microphone** — macOS will prompt automatically the first time you record;
   if you dismiss it, re-grant it under Privacy & Security -> Microphone.

Grant these to whatever process actually runs the app (your terminal, or the
built app bundle if you package one).

> **Known caveat:** `pystray`'s tray-icon event loop wants to run on the main
> thread on macOS, which conflicts with this build's assumption that Tk owns
> the main thread. If you're porting this to macOS, swap that: run `pystray`
> on the main thread and move the Tk overlay's `mainloop()` to a worker
> thread, or replace the Tk pill with an `NSWindow`-based one as in the
> original macOS-native design.

### Linux

- `pynput` global hotkeys require an **X11** session. Under **Wayland**,
  most compositors block global key listeners for security reasons, and the
  hotkey simply won't fire — there is no code fix for this, it's a platform
  limitation. Run under Xorg (or XWayland won't help — global hooks still
  need real X11) if you want this to work on Linux.

---

## Known limitations

- Clipboard save/restore only preserves **text**. If your clipboard held an
  image or file selection before you dictated, that's not restored — a
  limitation of the cross-platform clipboard libraries this build uses
  (the original macOS-native design using `NSPasteboard` directly could
  preserve every pasteboard item and type; this cross-platform version
  trades that fidelity for running everywhere).
- The floating "Listening..." pill is a plain Tk window, not a native
  non-activating overlay — on most window managers it won't steal focus, but
  this isn't guaranteed on every platform/WM the way a native
  `NSPanel`/`WS_EX_NOACTIVATE` window would guarantee it.
- No accounts, no telemetry, no update mechanism, no crash reporting — this
  is a minimal, single-purpose tool by design.

---

## Project structure

```
voce/
  run.py                  # entry point: python run.py
  requirements.txt
  LICENSE                 # MIT License
  settings.json            # your local config (hotkey, engine, model)
  .env                      # your local API keys (not committed)
  .env.example
  src/voce/
    app.py                 # orchestrates everything, owns the Tk mainloop
    config.py              # settings.json + .env loading
    audio.py                # microphone capture -> WAV
    hotkey.py               # global hold-to-talk listener
    transcribe.py            # whisper.cpp / Groq / OpenAI
    cleanup.py               # Claude cleanup pass
    paste.py                 # clipboard save + simulated paste + restore
    overlay.py                # the "Listening..." pill
    tray.py                    # tray icon + menu
    autostart.py                # launch-at-login (Windows/macOS/Linux)
```

---

## Troubleshooting

- **Nothing happens when I hold the hotkey.** Check the terminal for errors.
  On Linux, confirm you're on X11, not Wayland. On Windows, check that no
  antivirus is silently blocking the keyboard hook.
- **"whisper.cpp binary not found."** Your `transcription.local.binary_path`
  in `settings.json` doesn't point at your actual build output — check where
  `cmake --build` actually placed `whisper-cli.exe` and update the path.
- **Cleanup silently does nothing (raw text pastes unchanged).** This is
  expected if `ANTHROPIC_API_KEY` isn't set in `.env`, or `cleanup.enabled` is
  `false`. Check the terminal — a failed cleanup call logs a
  `[voce] cleanup failed, pasting raw transcript instead: ...` line rather
  than crashing. Before suspecting cleanup is doing something *wrong*
  (rather than nothing), confirm it's even running — it's a common
  misdiagnosis to blame cleanup for a transcription-side bug when no
  Anthropic key is set at all.
- **It pastes something unrelated, like "Thank you," when I didn't say
  anything (or said very little).** This is Whisper hallucinating — the
  model has no native way to say "there's no speech here," so near-silent
  audio makes it output a phrase from its training data instead, almost
  always "Thank you." (a lot of that training data is YouTube videos ending
  in "thanks for watching"). Fixed by `SILENCE_PEAK_AMPLITUDE` in
  `audio.py` — recordings whose loudest sample never exceeds that threshold
  are discarded before any transcription engine sees them. If real quiet
  speech starts getting silently dropped instead, lower that constant; if
  hallucinated pastes come back, raise it.
- **Cleanup answers a dictated question instead of cleaning it up** (e.g.
  dictating "how are you doing" pastes "Great!" instead of "How are you
  doing?"). This would happen if the raw transcript is indistinguishable
  from a real message to the model — a dictated question looks exactly like
  someone asking Claude a question. Hardened in `cleanup.py`: the transcript
  is wrapped in `<transcript>...</transcript>` tags with an explicit
  system-prompt instruction that its contents are dictation being
  transcribed, never a message addressed to the model. (Note: assistant
  message prefill was deliberately *not* used to enforce this — it 400s on
  current Claude models, e.g. Opus 4.6 and later.)
- **Pasted text lands in the wrong window.** Make sure the window you want to
  dictate into has focus *before* you hold the hotkey — Voce pastes wherever
  focus already is, it doesn't change focus itself.
- **It's recording from the wrong microphone** (you picked one in the tray
  menu but your built-in mic is clearly what's being heard). Check the
  console for a `[voce] WARNING: could not open input device ...` line —
  that means the selected device refused to open and Voce fell back to the
  system default. The usual cause is a sample-rate mismatch: under Windows
  WASAPI a device only accepts its native format, and some mics (phone-as-mic
  apps, some USB interfaces) are 48kHz-only while `sample_rate` defaults to
  16000. Voce now negotiates a supported rate automatically, so this should
  be rare — if it still happens, the device is genuinely unavailable
  (unplugged, or its companion app isn't running).
- **The last word of what I said comes out wrong or missing** (e.g. "what are
  you saying" pastes as "what are you"). This is releasing the hotkey right
  on the final syllable rather than a fraction of a second after it — the
  mic stops before Whisper hears the whole word. Confirmed by A/B testing
  the same recording trimmed to different tail lengths: cutting 150ms off
  the end still transcribed correctly, cutting 300ms lost the last word.
  Fixed as of the `CAPTURE_TAIL_SECONDS` constant in `app.py` (currently
  0.35s) — `Recorder.stop()` keeps the mic open for that long after you
  release the hotkey before cutting the clip. If this resurfaces (e.g. on a
  much slower or much faster talker), raise or lower that constant rather
  than re-diagnosing from scratch; it isn't a `settings.json` option because
  it's a fixed recording-pipeline behavior, not a per-user preference. Ruled
  out during diagnosis, so don't re-check these first: mic startup latency
  (measured at 6–45ms, too fast to clip anything), the local LLM cleanup
  pass (only runs if `ANTHROPIC_API_KEY` is set — verify with a print/log
  before suspecting it), and 16kHz-vs-44.1kHz mic resampling (A/B tested
  identical on the same phrase).

---

## License

Distributed under the [MIT License](LICENSE).

