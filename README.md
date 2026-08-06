# Wispr

A lightweight, offline-first, system-wide dictation tool. Hold a hotkey anywhere
on your system, speak, release — Wispr transcribes your speech, cleans it up
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

Wispr supports three transcription engines, configured in `settings.json` ->
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
Wispr pastes the raw transcript unmodified — dictation still works, you just
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
| `sample_rate` | `16000` | Microphone sample rate in Hz. 16kHz is what whisper.cpp expects. |
| `input_device` | `null` | Microphone/input device index, or `null` for the system default. Normally set from the tray menu's "Input Device" submenu, not edited by hand — takes effect on the next recording, no restart. |
| `transcription.engine` | `"local"` | `"local"`, `"groq"`, or `"openai"`. |
| `transcription.local.binary_path` | `whisper.cpp/build/bin/whisper-cli` | Path to the built whisper.cpp CLI binary. |
| `transcription.local.model_path` | `whisper.cpp/models/ggml-small.en.bin` | Path to the ggml model file. |
| `transcription.groq_model` | `"whisper-large-v3-turbo"` | Model name sent to the Groq API. |
| `transcription.openai_model` | `"whisper-1"` | Model name sent to the OpenAI API. |
| `transcription.language` | `"en"` | Language code used when `auto_detect_language` is `false`. Set from the tray menu's "Language" submenu (24 common languages); any Whisper language code works if you edit this by hand, even ones not in the tray list. Takes effect on the next recording. |
| `transcription.auto_detect_language` | `false` | When `true`, no fixed language is sent — the engine detects it per recording. Toggled from the tray menu. The detected language is printed to the console and briefly flashed in the pill. |
| `cleanup.enabled` | `true` | Whether to run the LLM cleanup pass. |
| `cleanup.model` | `"claude-haiku-4-5"` | Any Claude model ID. Haiku 4.5 is the recommended default — it's fast and cheap, which matters for a latency-sensitive dictation pass. |
| `launch_at_login` | `false` | Kept in sync automatically when you toggle it from the tray menu. |

`input_device`, `transcription.language`, `transcription.auto_detect_language`,
`hotkey`, and `hotkey_mode` are normally changed from the tray menu (which
also writes them back to this file) and apply immediately, no restart.
Everything else requires editing `settings.json` directly and restarting
Wispr.

---

## Permissions

### Windows

- **Microphone:** Windows will prompt for microphone access the first time
  Wispr records, or you can pre-grant it under
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
wispr/
  run.py                  # entry point: python run.py
  requirements.txt
  LICENSE                 # MIT License
  settings.json            # your local config (hotkey, engine, model)
  .env                      # your local API keys (not committed)
  .env.example
  src/wispr/
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
  `[wispr] cleanup failed, pasting raw transcript instead: ...` line rather
  than crashing.
- **Pasted text lands in the wrong window.** Make sure the window you want to
  dictate into has focus *before* you hold the hotkey — Wispr pastes wherever
  focus already is, it doesn't change focus itself.

---

## License

Distributed under the [MIT License](LICENSE).

