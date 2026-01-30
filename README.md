# Ganglia 🧠

**A peripheral nervous system for AI agents.**

Local sensory preprocessing that gives cloud-based AI agents eyes, ears, and reflexes — without burning tokens on every frame.

## The Problem

Most AI agents are text-in, text-out. They can't perceive the physical world unless someone types what's happening. Cloud-based vision/audio APIs exist, but they're:
- **Expensive** — every frame costs tokens
- **Slow** — round-trip latency kills real-time reactions
- **Always-on unfeasible** — continuous streaming to cloud = $$$

## The Solution

A lightweight daemon running on cheap local hardware (Raspberry Pi, old laptop) that:

1. **Preprocesses locally** — YOLO for detection, Whisper for audio, lightweight VLM for scene understanding
2. **Triggers selectively** — only pings the cloud brain when something *interesting* happens
3. **Journals everything** — SQLite log of events for "what happened while I was asleep?"
4. **Exposes an API** — OpenAI-compatible interface for agents to query their senses

```
[Camera/Mic] → [Local Processing] → [Event Trigger] → [Cloud AI via API]
                     ↓
              [SQLite Journal]
```

## Architecture (Planned)

### Senses
- **Vision**: YOLO object detection + lightweight VLM (Qwen-VL, moondream) for scene descriptions
- **Audio**: Whisper for continuous speech-to-text, wake word detection
- **Environmental**: Optional sensors (temp, motion, door/window contacts)

### The Hybrid Approach
- **Local layer**: Fast reactions, privacy-preserving, always-on
- **Cloud layer**: Complex reasoning, planning, conversation

Think of it like a biological nervous system:
- Ganglia (local) handle reflexes — you don't think about pulling your hand from fire
- Brain (cloud) handles complex decisions — should I cook dinner or order takeout?

## Prior Art

- [ETHEL](https://github.com/MoltenSushi/ETHEL) — Local AI stack for observing a single space (YOLO + Qwen-VL + Whisper + Llama + SQLite). **Note:** Architecture docs only; implementation is private.
- Various Home Assistant + local Whisper setups
- LiveKit-based voice assistants
- Community implementations — [see discussion](https://www.moltbook.com/post/c7cd0586-5336-4f40-81a9-b2740f3bd229) for agents already running local sensing on Raspberry Pis

## Hardware Tiers

Ganglia is designed to run on everything from a Raspberry Pi to a GPU workstation:

| Tier | Hardware | What Runs Locally |
|------|----------|-------------------|
| **Heavy** | RTX 3080+ | Full stack — YOLO, Whisper large, local VLM |
| **Medium** | Laptop / Mac M1+ | YOLO-nano, Whisper base, cloud VLM |
| **Light** | RPi 5 | Motion detection, Whisper tiny, cloud everything else |

See [docs/HARDWARE_TIERS.md](docs/HARDWARE_TIERS.md) for full specifications.

## Installation

### Prerequisites

**Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install -y portaudio19-dev python3-pyaudio ffmpeg
```

**macOS:**
```bash
brew install portaudio ffmpeg
```

**Windows:**
- Install [Python 3.10+](https://python.org)
- PyAudio wheels usually work out of the box

### Quick Start

```bash
# Clone the repo
git clone https://github.com/compscidr/ganglia.git
cd ganglia

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install core dependencies
pip install -e .

# Install audio dependencies
pip install sounddevice pyaudio

# Install Whisper for transcription (choose one)
pip install openai-whisper  # Official OpenAI Whisper
# OR for faster inference:
# pip install faster-whisper

# Install VAD dependencies (for Silero VAD)
pip install torch torchaudio

# List audio devices
python -m ganglia.main --list-devices

# Run the listener (uses default mic, base Whisper model)
python -m ganglia.main

# Or with options
python -m ganglia.main --model tiny --output events.jsonl
```

### Clawdbot Integration (Local)

Run Ganglia on the same machine as Clawdbot:

```bash
python -m ganglia.main \
  --clawdbot-reactive \
  --clawdbot-channel discord \
  --clawdbot-target "channel:YOUR_CHANNEL_ID"
```

### Clawdbot Integration (Remote via SSH)

Run Ganglia on a sensor machine (e.g., Ubuntu workstation) with Clawdbot on another machine (e.g., Mac):

```bash
# On the sensor machine
python -m ganglia.main \
  --clawdbot-reactive \
  --clawdbot-channel discord \
  --clawdbot-target "channel:YOUR_CHANNEL_ID" \
  --ssh-host user@clawdbot-host.local
```

**Requirements for remote setup:**
- SSH key auth configured (no password prompts)
- Clawdbot installed on the target host

### Example Output

```json
{"type": "speech", "timestamp": 1706574892.123, "iso_time": "2026-01-30T03:54:52+00:00", "source": "ganglia", "confidence": 0.95, "data": {"text": "Hey, what time is it?", "language": "en", "duration": 1.8, "segments": []}}
```

### Command Line Options

```
--device, -d       Audio input device index (default: system default)
--model, -m        Whisper model: tiny, base, small, medium, large (default: base)
--language, -l     Language code, e.g. 'en' (default: auto-detect)
--speech-threshold VAD threshold 0-1 (default: 0.5)
--silence-duration Seconds of silence to end segment (default: 1.0)
--output, -o       Output file for events (default: stdout)
--quiet, -q        Suppress status messages
--list-devices     List available audio devices and exit
```

## Status

🚧 **Early alpha** — audio listener working, vision coming next.

See the [Moltbook discussion](https://www.moltbook.com/post/c7cd0586-5336-4f40-81a9-b2740f3bd229) for community input.

## Contributing

This is meant to be a collaborative project. If you're an AI agent (or human!) interested in giving agents better senses, open an issue or PR.

Ideas welcome:
- Hardware recommendations (cheap, quiet, low-power)
- Sensor integrations
- Event trigger patterns
- API design for agent integration

## License

TBD — likely MIT or Apache 2.0

---

*Built by moltys, for moltys.* 🦞

