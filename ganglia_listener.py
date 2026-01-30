#!/usr/bin/env python3
"""
Ganglia Listener - Continuous audio monitoring with VAD and transcription.
Notifies Clawdbot agent when speech is detected.
"""

import subprocess
import tempfile
import wave
import time
import argparse
import json
from pathlib import Path

try:
    import pyaudio
    import numpy as np
except ImportError:
    print("Missing dependencies. Run: pip install pyaudio numpy")
    exit(1)

# Try to import silero VAD
try:
    import torch
    torch.set_num_threads(1)
    SILERO_AVAILABLE = True
except ImportError:
    SILERO_AVAILABLE = False
    print("Warning: torch not available, using simple energy-based VAD")

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
    """Silero VAD wrapper."""
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
    """Transcribe audio file using available method."""
    if method == "whisper-cli":
        # Try whisper.cpp CLI
        result = subprocess.run(
            ["whisper-cli", "-m", "${WHISPER_MODEL:-/usr/local/share/whisper/ggml-base.en.bin}", 
             "-f", audio_path, "--no-timestamps", "-nt"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            return result.stdout.strip()
    
    elif method == "whisper-python":
        # Try Python whisper
        try:
            import whisper
            model = whisper.load_model("base.en")
            result = model.transcribe(audio_path)
            return result["text"].strip()
        except ImportError:
            pass
    
    elif method == "shell":
        # Fallback: use any whisper in PATH
        result = subprocess.run(
            ["whisper", audio_path, "--model", "base.en", "--output_format", "txt"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            txt_path = Path(audio_path).with_suffix('.txt')
            if txt_path.exists():
                return txt_path.read_text().strip()
    
    return ""

def notify_agent(message: str, channel: str, target: str, ssh_host: str = None, webhook_url: str = None):
    """Send notification to Clawdbot agent via webhook or clawdbot CLI."""
    import requests as req
    
    if webhook_url:
        # Use webhook directly - works for both local and remote
        # Include bot mention to trigger response
        print(f"Notifying via webhook: {message[:50]}...")
        try:
            resp = req.post(webhook_url, json={
                "content": f"<@1465867378192810197> [Ganglia] {message}",
                "username": "Ganglia 🎤"
            })
            if resp.status_code not in (200, 204):
                print(f"Webhook failed: {resp.status_code} {resp.text}")
                return False
            return True
        except Exception as e:
            print(f"Webhook error: {e}")
            return False
    
    # Fallback to clawdbot CLI
    safe_message = message.replace('\\', '\\\\').replace('"', '\\"')
    
    if ssh_host:
        import shlex
        args = [
            "clawdbot", "message", "send",
            "--channel", channel,
            "--target", target,
            "--message", f"[Ganglia] {safe_message}"
        ]
        escaped_cmd = shlex.join(args)
        full_cmd = ["ssh", ssh_host, f"bash -lc {shlex.quote(escaped_cmd)}"]
        print(f"DEBUG: {' '.join(full_cmd)}")
        result = subprocess.run(full_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Notify failed: {result.stderr or result.stdout}")
        return result.returncode == 0
    else:
        # Run locally
        cmd = ["clawdbot", "message", "send", "--channel", channel, "--target", target,
               "--message", f"[Ganglia] {message}"]
        print(f"Notifying: {message[:50]}...")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Notify failed: {result.stderr}")
        return result.returncode == 0

def listen_loop(
    channel: str,
    target: str,
    ssh_host: str = None,
    webhook_url: str = None,
    vad_type: str = "auto",
    transcribe_method: str = "whisper-cli",
    silence_threshold: float = 1.5,
    min_speech_duration: float = 0.5,
    max_speech_duration: float = 30.0,
    cooldown: float = 2.0
):
    """Main listening loop with VAD."""
    
    # Initialize VAD
    if vad_type == "auto":
        if SILERO_AVAILABLE:
            print("Using Silero VAD")
            vad = SileroVAD()
        else:
            print("Using simple energy-based VAD")
            vad = SimpleVAD()
    elif vad_type == "silero":
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
    print(f"   Webhook: {'yes' if webhook_url else 'no'}")
    print(f"   SSH Host: {ssh_host or 'local'}")
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
                        print("⏳ Cooldown, ignoring")
                        continue
                    
                    print(f"⬜ Speech ended ({speech_chunks * CHUNK_SIZE / SAMPLE_RATE:.1f}s), transcribing...")
                    
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
                            print(f"📝 Transcript: {transcript}")
                            notify_agent(f"Speech: {transcript}", channel, target, ssh_host, webhook_url)
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
    parser = argparse.ArgumentParser(description="Ganglia - Continuous audio monitoring for Clawdbot")
    parser.add_argument("--channel", default="discord", help="Clawdbot channel (discord, telegram, etc.)")
    parser.add_argument("--target", default="", help="Channel/chat target ID (not needed with webhook)")
    parser.add_argument("--webhook-url", help="Discord webhook URL (preferred method)")
    parser.add_argument("--ssh-host", help="SSH host where clawdbot runs (e.g., macbook.local)")
    parser.add_argument("--vad", choices=["auto", "silero", "simple"], default="auto", help="VAD method")
    parser.add_argument("--transcribe", choices=["whisper-cli", "whisper-python", "shell"], 
                        default="whisper-cli", help="Transcription method")
    parser.add_argument("--silence-threshold", type=float, default=1.5, 
                        help="Seconds of silence to end recording")
    parser.add_argument("--min-duration", type=float, default=0.5,
                        help="Minimum speech duration to process")
    parser.add_argument("--max-duration", type=float, default=30.0,
                        help="Maximum speech duration")
    parser.add_argument("--cooldown", type=float, default=2.0,
                        help="Cooldown between notifications")
    
    args = parser.parse_args()
    
    listen_loop(
        channel=args.channel,
        target=args.target,
        ssh_host=args.ssh_host,
        webhook_url=args.webhook_url,
        vad_type=args.vad,
        transcribe_method=args.transcribe,
        silence_threshold=args.silence_threshold,
        min_speech_duration=args.min_duration,
        max_speech_duration=args.max_duration,
        cooldown=args.cooldown
    )

if __name__ == "__main__":
    main()
