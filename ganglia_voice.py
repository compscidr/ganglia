#!/usr/bin/env python3
"""
Ganglia Voice - Full duplex voice communication with Clawdbot.

Runs both:
1. Listener: Captures speech → transcribes → sends to Clawdbot
2. Response handler: Receives Clawdbot responses → TTS → speaks

## Quick Start

    # Install dependencies
    pip install pyaudio numpy torch piper-tts
    
    # Download Piper voice model
    mkdir -p ~/.local/share/piper
    wget -O ~/.local/share/piper/en_US-lessac-medium.onnx \
        https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx
    wget -O ~/.local/share/piper/en_US-lessac-medium.onnx.json \
        https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json

    # Run (local)
    python ganglia_voice.py --channel discord --target channel:1234567890
    
    # Run (remote - Clawdbot on Mac)
    python ganglia_voice.py --channel discord --target channel:1234567890 \\
        --ssh-host jason@macbook.local --speaker "Jason"
"""

import argparse
import sys
import threading
import signal

def main():
    parser = argparse.ArgumentParser(
        description="Ganglia Voice - Full duplex voice communication with Clawdbot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Local (Ganglia and Clawdbot on same machine)
    %(prog)s --channel discord --target channel:1234567890

    # Remote (Ganglia on Ubuntu, Clawdbot on Mac)
    %(prog)s --channel discord --target channel:1234567890 \\
        --ssh-host jason@macbook.local --speaker "Jason"
"""
    )
    
    # Clawdbot connection
    parser.add_argument("--channel", default="discord",
                        help="Clawdbot channel type (discord, telegram, etc.)")
    parser.add_argument("--target", required=True,
                        help="Target within channel (e.g., channel:1234567890)")
    parser.add_argument("--ssh-host",
                        help="SSH host where Clawdbot runs")
    parser.add_argument("--speaker",
                        help="Speaker name for attribution")
    
    # TTS options
    parser.add_argument("--tts-model", default="en_US-lessac-medium",
                        help="Piper TTS model name or path")
    parser.add_argument("--no-tts", action="store_true",
                        help="Disable TTS response handler (listen only)")
    
    # Face visualization
    parser.add_argument("--face", action="store_true",
                        help="Show ocean wave face visualization")
    
    # Transcription options
    parser.add_argument("--transcribe", default="whisper-cli",
                        choices=["whisper-cli", "whisper-python", "shell"],
                        help="Transcription method")
    
    # VAD options
    parser.add_argument("--vad", default="auto",
                        choices=["auto", "silero", "simple"],
                        help="VAD method")
    
    args = parser.parse_args()
    
    # Import here to avoid import errors if deps missing
    from ganglia_listener import listen_loop
    
    # Shared event for echo suppression - set while TTS is speaking
    speaking_event = threading.Event()
    
    # Start TTS response handler in background thread
    response_thread = None
    handler = None
    if not args.no_tts:
        try:
            from ganglia.integrations.response_handler import create_response_handler
            handler = create_response_handler(
                tts_engine="piper",
                model=args.tts_model,
            )
            # Share the speaking event for echo suppression
            handler.speaking_event = speaking_event
            
            response_thread = threading.Thread(
                target=handler.start,
                kwargs={"blocking": True},
                daemon=True,
            )
            response_thread.start()
            print("🔊 TTS response handler started (with echo suppression)")
        except Exception as e:
            print(f"⚠️ Could not start TTS handler: {e}")
            print("   Continuing without TTS (listen only)")
            speaking_event = None  # No echo suppression needed
    
    # Start face visualization if requested
    face = None
    face_thread = None
    if args.face:
        try:
            from ganglia.face.ocean import OceanFace
            face = OceanFace()
            face_thread = threading.Thread(target=face.run, daemon=True)
            face_thread.start()
            print("🌊 Face visualization started")
        except Exception as e:
            print(f"⚠️ Could not start face: {e}")
            print("   (Try: pip install pygame)")
    
    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        print("\n\n👋 Shutting down Ganglia Voice...")
        # Stop face visualization cleanly
        if face:
            face.stop()
            import time
            time.sleep(0.2)  # Give pygame time to quit
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    # Start listener (blocks)
    print("🎤 Starting voice listener...")
    listen_loop(
        channel=args.channel,
        target=args.target,
        ssh_host=args.ssh_host,
        speaker=args.speaker,
        vad_type=args.vad,
        transcribe_method=args.transcribe,
        speaking_event=speaking_event,  # For echo suppression
    )


if __name__ == "__main__":
    main()
