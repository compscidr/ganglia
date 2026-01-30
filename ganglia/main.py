#!/usr/bin/env python3
"""
Ganglia - Local sensory preprocessing for AI agents.

This is the main entry point for the audio listener.
Listens to microphone, detects speech, transcribes, and emits events.
"""

import argparse
import sys
import threading
from typing import Optional

from ganglia.audio.listener import AudioListener, list_devices
from ganglia.audio.transcribe import Transcriber
from ganglia.audio.speaker import Speaker
from ganglia.events import EventEmitter, speech_event
from ganglia.integrations.clawdbot import create_clawdbot_handler


def main():
    parser = argparse.ArgumentParser(
        description="Ganglia audio listener - local speech detection and transcription"
    )
    
    # Audio settings
    parser.add_argument(
        "--device", "-d",
        type=int,
        default=None,
        help="Audio input device index (default: system default)"
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List available audio devices and exit"
    )
    
    # Video settings
    parser.add_argument(
        "--vision",
        action="store_true",
        help="Enable vision - capture frame when 'what do you see' is detected"
    )
    parser.add_argument(
        "--camera",
        type=int,
        default=0,
        help="Camera device index (default: 0)"
    )
    
    # Model settings
    parser.add_argument(
        "--model", "-m",
        default="base",
        choices=["tiny", "tiny.en", "base", "base.en", "small", "small.en", "medium", "large"],
        help="Whisper model size (default: base)"
    )
    parser.add_argument(
        "--language", "-l",
        default=None,
        help="Language code (default: auto-detect)"
    )
    
    # VAD settings
    parser.add_argument(
        "--speech-threshold",
        type=float,
        default=0.5,
        help="Speech detection threshold 0-1 (default: 0.5)"
    )
    parser.add_argument(
        "--silence-duration",
        type=float,
        default=1.0,
        help="Seconds of silence to end speech segment (default: 1.0)"
    )
    
    # TTS settings
    parser.add_argument(
        "--tts",
        action="store_true",
        help="Enable TTS speaker - watches queue and speaks responses"
    )
    parser.add_argument(
        "--tts-engine",
        default="espeak",
        choices=["espeak", "pyttsx3", "say"],
        help="TTS engine (default: espeak for Linux, say for macOS)"
    )
    
    # Face visualization
    parser.add_argument(
        "--face",
        action="store_true",
        help="Show Kai's ocean face visualization (reacts to TTS)"
    )
    
    # Output settings
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output file for events (default: stdout)"
    )
    parser.add_argument(
        "--clawdbot",
        action="store_true",
        help="Write events to Clawdbot integration file (~/.clawdbot/ganglia-events.jsonl)"
    )
    parser.add_argument(
        "--clawdbot-reactive",
        action="store_true",
        help="Trigger Clawdbot agent immediately on speech (reactive mode)"
    )
    parser.add_argument(
        "--clawdbot-channel",
        default="discord",
        help="Clawdbot delivery channel (default: discord)"
    )
    parser.add_argument(
        "--clawdbot-target",
        default="channel:1465867928724439043",
        help="Clawdbot reply target (default: channel:1465867928724439043)"
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress status messages, only output events"
    )
    
    args = parser.parse_args()
    
    # List devices and exit
    if args.list_devices:
        list_devices()
        return 0
    
    # Set up event emitter
    emitter = EventEmitter()
    if args.clawdbot or args.clawdbot_reactive:
        handler = create_clawdbot_handler(
            reactive=args.clawdbot_reactive,
            channel=args.clawdbot_channel,
            reply_to=args.clawdbot_target
        )
        emitter.add_handler(handler)
        if not args.quiet:
            if args.clawdbot_reactive:
                print(f"🤖 Reactive mode: will trigger Clawdbot on speech")
            else:
                print(f"🤖 Writing events to Clawdbot (~/.clawdbot/ganglia-events.jsonl)")
    if args.output:
        emitter.add_file_handler(args.output)
        if not args.quiet:
            print(f"📁 Writing events to: {args.output}")
    if not args.clawdbot and not args.clawdbot_reactive and not args.output:
        emitter.add_stdout_handler()
    
    # Initialize TTS speaker if enabled
    speaker = None
    speaker_thread = None
    if args.tts:
        speaker = Speaker(tts_engine=args.tts_engine)
        speaker_thread = threading.Thread(target=speaker.watch_queue, daemon=True)
        speaker_thread.start()
        if not args.quiet:
            print(f"🔊 TTS enabled (engine: {args.tts_engine})")
    
    # Initialize face visualization if enabled
    face_process = None
    if args.face:
        import subprocess
        import sys
        # Run face in separate process (macOS requires GUI on main thread)
        face_process = subprocess.Popen(
            [sys.executable, "-m", "ganglia.face.ocean"],
            # Don't suppress output so we can see errors
        )
        if not args.quiet:
            print(f"🌊 Face visualization enabled (pid: {face_process.pid})")
    
    # Initialize components
    if not args.quiet:
        print("="*50)
        print("🧠 Ganglia Audio Listener")
        print("="*50)
    
    listener = AudioListener(
        device=args.device,
        speech_threshold=args.speech_threshold,
        silence_duration=args.silence_duration,
    )
    
    transcriber = Transcriber(
        model_size=args.model,
        language=args.language,
    )
    
    if not args.quiet:
        print(f"🎤 Using model: {args.model}")
        print(f"🔊 Speech threshold: {args.speech_threshold}")
        print(f"⏱️  Silence duration: {args.silence_duration}s")
        print("="*50)
        print("Listening... (Ctrl+C to stop)")
        print()
    
    # Main loop
    try:
        for chunk in listener.listen():
            if not args.quiet:
                print(f"🎙️  Speech detected ({chunk.duration:.1f}s), transcribing...")
            
            # Transcribe
            result = transcriber.transcribe(chunk.audio, chunk.sample_rate)
            
            if result.text.strip():
                # Check for vision triggers
                text_lower = result.text.lower()
                vision_triggers = ["what do you see", "look at", "can you see", "show me what", "take a picture", "take a photo"]
                should_capture = args.vision and any(t in text_lower for t in vision_triggers)
                
                if should_capture:
                    if not args.quiet:
                        print(f"   👁️ Vision trigger detected, capturing frame...")
                    try:
                        from ganglia.video import capture_frame, describe_frame_clawdbot
                        frame = capture_frame(device=args.camera)
                        if frame:
                            describe_frame_clawdbot(frame, f"The user said: \"{result.text}\". Describe what you see and respond to their request.")
                            if not args.quiet:
                                print(f"   📷 Frame sent for analysis")
                            # Skip speech event - vision handler already triggered agent
                            continue
                        else:
                            if not args.quiet:
                                print(f"   ⚠️ Failed to capture frame")
                    except Exception as e:
                        if not args.quiet:
                            print(f"   ⚠️ Vision error: {e}")
                
                # Emit event (only if vision didn't handle it)
                event = speech_event(
                    text=result.text,
                    language=result.language,
                    duration=result.duration,
                    confidence=result.confidence,
                    segments=result.segments
                )
                emitter.emit(event)
                
                if not args.quiet and args.output:
                    # Also print to console if outputting to file
                    print(f"   📝 \"{result.text}\"")
            else:
                if not args.quiet:
                    print(f"   (no speech detected)")
                    
    except KeyboardInterrupt:
        if speaker:
            speaker.stop()
        if face_process:
            face_process.terminate()
        if not args.quiet:
            print("\n\n👋 Stopped.")
        return 0
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
