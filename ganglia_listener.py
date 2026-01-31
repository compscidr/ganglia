#!/usr/bin/env python3
"""
Ganglia Listener - Continuous audio monitoring with VAD and transcription.

Listens for speech, transcribes it using Whisper, and sends to a Clawdbot
agent session. Supports local and remote (SSH) setups.

## Quick Start

Local (Ganglia and Clawdbot on same machine):
    python ganglia_listener.py --channel discord --target channel:1234567890

Remote (Ganglia on Ubuntu, Clawdbot on Mac):
    python ganglia_listener.py --channel discord --target channel:1234567890 \\
        --ssh-host jason@macbook.local --speaker "Jason"

## Session Discovery

The listener automatically discovers the Clawdbot session ID by querying
`clawdbot sessions list`. No manual session ID management required.

## Requirements

    pip install pyaudio numpy torch  # torch is optional, enables better VAD
    
For whisper transcription, install whisper.cpp:
    brew install whisper-cpp  # or build from source
"""

import subprocess
import tempfile
import wave
import time
import argparse
import sys
from pathlib import Path

try:
    import pyaudio
    import numpy as np
except ImportError:
    print("Missing dependencies. Run: pip install pyaudio numpy")
    sys.exit(1)

# Try to import silero VAD (optional, falls back to energy-based)
try:
    import torch
    torch.set_num_threads(1)
    SILERO_AVAILABLE = True
except ImportError:
    SILERO_AVAILABLE = False

# Audio settings
SAMPLE_RATE = 16000
CHUNK_SIZE = 512  # 32ms at 16kHz
CHANNELS = 1
FORMAT = pyaudio.paInt16


class SimpleVAD:
    """Simple energy-based voice activity detection."""
    def __init__(self, threshold=0.01):
        self.threshold = threshold
    
    def __call__(self, audio_chunk):
        audio = np.frombuffer(audio_chunk, dtype=np.int16).astype(np.float32) / 32768.0
        energy = np.sqrt(np.mean(audio ** 2))
        return energy > self.threshold


class SileroVAD:
    """Silero VAD wrapper - more accurate than energy-based."""
    def __init__(self):
        self.model, self.utils = torch.hub.load(
            repo_or_dir='snakers4/silero-vad',
            model='silero_vad',
            force_reload=False
        )
        self.model.eval()
    
    def __call__(self, audio_chunk):
        audio = np.frombuffer(audio_chunk, dtype=np.int16).astype(np.float32) / 32768.0
        audio_tensor = torch.from_numpy(audio)
        speech_prob = self.model(audio_tensor, SAMPLE_RATE).item()
        return speech_prob > 0.5


def transcribe_audio(audio_path: str, method: str = "whisper-cli") -> str:
    """
    Transcribe audio file using Whisper.
    
    Methods:
        - whisper-cli: whisper.cpp CLI (fastest, recommended)
        - whisper-python: OpenAI whisper Python package
        - shell: Generic whisper command
    """
    if method == "whisper-cli":
        # whisper.cpp CLI
        import os
        model_path = os.environ.get("WHISPER_MODEL", "/usr/local/share/whisper/ggml-base.en.bin")
        result = subprocess.run(
            ["whisper-cli", "-m", model_path, "-f", audio_path, "--no-timestamps", "-nt"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            return result.stdout.strip()
    
    elif method == "whisper-python":
        try:
            import whisper
            model = whisper.load_model("base.en")
            result = model.transcribe(audio_path)
            return result["text"].strip()
        except ImportError:
            print("whisper-python not installed. Run: pip install openai-whisper")
    
    elif method == "shell":
        result = subprocess.run(
            ["whisper", audio_path, "--model", "base.en", "--output_format", "txt"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            txt_path = Path(audio_path).with_suffix('.txt')
            if txt_path.exists():
                return txt_path.read_text().strip()
    
    return ""


def listen_loop(
    channel: str,
    target: str,
    ssh_host: str = None,
    speaker: str = None,
    vad_type: str = "auto",
    transcribe_method: str = "whisper-cli",
    silence_threshold: float = 1.5,
    min_speech_duration: float = 0.5,
    max_speech_duration: float = 30.0,
    cooldown: float = 2.0
):
    """
    Main listening loop with VAD.
    
    Continuously listens for speech, transcribes when detected, and sends
    to the configured Clawdbot session.
    """
    # Import integration here to avoid import errors if dependencies missing
    from ganglia.integrations.clawdbot import ClawdbotIntegration
    
    # Initialize Clawdbot integration
    speaker_label = f'{speaker} said:' if speaker else None
    integration = ClawdbotIntegration(
        channel=channel,
        target=target,
        ssh_host=ssh_host,
        reactive=True,
        speaker_label=speaker_label,
    )
    
    # Pre-discover session ID so we fail early if something's wrong
    print("🔍 Discovering Clawdbot session...")
    session_id = integration.get_session_id()
    if not session_id:
        print("❌ Failed to discover session. Check that:")
        print(f"   - Clawdbot is running with channel={channel}")
        print(f"   - A session exists for target={target}")
        if ssh_host:
            print(f"   - SSH to {ssh_host} works")
        sys.exit(1)
    
    # Initialize VAD
    if vad_type == "auto":
        if SILERO_AVAILABLE:
            print("🎯 Using Silero VAD (neural network)")
            vad = SileroVAD()
        else:
            print("🎯 Using energy-based VAD (install torch for better accuracy)")
            vad = SimpleVAD()
    elif vad_type == "silero":
        if not SILERO_AVAILABLE:
            print("❌ Silero VAD requires torch. Run: pip install torch")
            sys.exit(1)
        vad = SileroVAD()
    else:
        vad = SimpleVAD()
    
    # Initialize audio
    pa = pyaudio.PyAudio()
    stream = pa.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=SAMPLE_RATE,
        input=True,
        frames_per_buffer=CHUNK_SIZE
    )
    
    print(f"\n🎤 Ganglia listening...")
    print(f"   Channel: {channel}")
    print(f"   Target: {target}")
    print(f"   SSH Host: {ssh_host or 'local'}")
    print(f"   Speaker: {speaker or '(anonymous)'}")
    print(f"   Session: {session_id[:20]}...")
    print(f"   Press Ctrl+C to stop\n")
    
    recording = False
    audio_buffer = []
    silence_chunks = 0
    speech_chunks = 0
    last_notify_time = 0
    
    silence_chunks_threshold = int(silence_threshold * SAMPLE_RATE / CHUNK_SIZE)
    min_speech_chunks = int(min_speech_duration * SAMPLE_RATE / CHUNK_SIZE)
    max_speech_chunks = int(max_speech_duration * SAMPLE_RATE / CHUNK_SIZE)
    
    try:
        while True:
            chunk = stream.read(CHUNK_SIZE, exception_on_overflow=False)
            is_speech = vad(chunk)
            
            if is_speech:
                if not recording:
                    print("🔴 Speech detected, recording...")
                    recording = True
                    audio_buffer = []
                    silence_chunks = 0
                    speech_chunks = 0
                
                audio_buffer.append(chunk)
                speech_chunks += 1
                silence_chunks = 0
                
                # Check max duration
                if speech_chunks >= max_speech_chunks:
                    print("⚠️  Max duration reached, processing...")
                    silence_chunks = silence_chunks_threshold
            
            elif recording:
                audio_buffer.append(chunk)
                silence_chunks += 1
                
                # End of speech?
                if silence_chunks >= silence_chunks_threshold:
                    recording = False
                    
                    # Check minimum duration
                    if speech_chunks < min_speech_chunks:
                        print("⏭️  Too short, ignoring")
                        continue
                    
                    # Check cooldown
                    if time.time() - last_notify_time < cooldown:
                        print("⏳ Cooldown active, ignoring")
                        continue
                    
                    duration = speech_chunks * CHUNK_SIZE / SAMPLE_RATE
                    print(f"⬜ Speech ended ({duration:.1f}s), transcribing...")
                    
                    # Save audio to temp file
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                        wf = wave.open(f.name, 'wb')
                        wf.setnchannels(CHANNELS)
                        wf.setsampwidth(pa.get_sample_size(FORMAT))
                        wf.setframerate(SAMPLE_RATE)
                        wf.writeframes(b''.join(audio_buffer))
                        wf.close()
                        
                        # Transcribe
                        transcript = transcribe_audio(f.name, transcribe_method)
                        
                        if transcript:
                            print(f"📝 \"{transcript}\"")
                            
                            # Create event and send to Clawdbot
                            from ganglia.events import Event, EventType
                            import time as time_module
                            event = Event(
                                type=EventType.SPEECH,
                                timestamp=time_module.time(),
                                data={
                                    "text": transcript,
                                    "duration": duration,
                                    "language": "en",
                                }
                            )
                            integration.handle_event(event)
                            last_notify_time = time.time()
                        else:
                            print("❌ Transcription failed or empty")
                        
                        # Cleanup
                        Path(f.name).unlink(missing_ok=True)
    
    except KeyboardInterrupt:
        print("\n\n👋 Stopping Ganglia listener...")
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()


def main():
    parser = argparse.ArgumentParser(
        description="Ganglia - Voice-to-agent bridge for Clawdbot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Local setup (Ganglia and Clawdbot on same machine)
  %(prog)s --channel discord --target channel:1234567890

  # Remote setup (Ganglia on Ubuntu, Clawdbot on Mac)
  %(prog)s --channel discord --target channel:1234567890 \\
      --ssh-host jason@macbook.local --speaker "Jason"

  # Telegram instead of Discord
  %(prog)s --channel telegram --target chat:1234567890

Session Discovery:
  The listener automatically discovers the Clawdbot session UUID by
  querying `clawdbot sessions list`. The session ID is cached in
  ~/.clawdbot/ganglia-session-id (on the Clawdbot host).
  
  If the session changes (e.g., after Clawdbot restart), it will be
  re-discovered automatically on the next speech event.
"""
    )
    
    # Required arguments
    parser.add_argument("--channel", default="discord",
                        help="Clawdbot channel type (discord, telegram, signal, etc.)")
    parser.add_argument("--target", required=True,
                        help="Target within channel (e.g., channel:1234567890 for Discord)")
    
    # Remote setup
    parser.add_argument("--ssh-host",
                        help="SSH host where Clawdbot runs (e.g., user@macbook.local)")
    parser.add_argument("--speaker",
                        help="Speaker name for attribution (e.g., 'Jason')")
    
    # VAD options
    parser.add_argument("--vad", choices=["auto", "silero", "simple"], default="auto",
                        help="VAD method: auto (best available), silero (neural), simple (energy)")
    
    # Transcription options
    parser.add_argument("--transcribe", choices=["whisper-cli", "whisper-python", "shell"],
                        default="whisper-cli",
                        help="Transcription method")
    
    # Timing options
    parser.add_argument("--silence-threshold", type=float, default=1.5,
                        help="Seconds of silence to end recording (default: 1.5)")
    parser.add_argument("--min-duration", type=float, default=0.5,
                        help="Minimum speech duration to process (default: 0.5)")
    parser.add_argument("--max-duration", type=float, default=30.0,
                        help="Maximum speech duration (default: 30.0)")
    parser.add_argument("--cooldown", type=float, default=2.0,
                        help="Cooldown between notifications (default: 2.0)")
    
    args = parser.parse_args()
    
    listen_loop(
        channel=args.channel,
        target=args.target,
        ssh_host=args.ssh_host,
        speaker=args.speaker,
        vad_type=args.vad,
        transcribe_method=args.transcribe,
        silence_threshold=args.silence_threshold,
        min_speech_duration=args.min_duration,
        max_speech_duration=args.max_duration,
        cooldown=args.cooldown
    )


if __name__ == "__main__":
    main()
