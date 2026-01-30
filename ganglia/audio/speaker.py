"""
Audio speaker module - plays TTS responses locally.
Watches for audio to play and outputs through speakers.
"""

import subprocess
import threading
import time
from pathlib import Path
from typing import Optional
import json


class Speaker:
    """
    Plays audio responses through local speakers.
    
    Can use local TTS (pyttsx3/espeak) or play audio files.
    Sets a "speaking" flag that the listener can check to pause VAD.
    """
    
    def __init__(
        self,
        tts_engine: str = "espeak",  # espeak, pyttsx3, or file
        voice: Optional[str] = None,
        rate: int = 175,  # words per minute
    ):
        self.tts_engine = tts_engine
        self.voice = voice
        self.rate = rate
        self._queue_file = Path.home() / ".clawdbot" / "ganglia-tts-queue.jsonl"
        self._speaking_file = Path.home() / ".clawdbot" / "ganglia-speaking"
        self._running = False
        self.is_speaking = False
        
    def _set_speaking(self, speaking: bool):
        """Set the speaking flag (used to pause listener)."""
        self.is_speaking = speaking
        if speaking:
            self._speaking_file.touch()
        else:
            self._speaking_file.unlink(missing_ok=True)
    
    def speak(self, text: str):
        """Speak text through local TTS."""
        if not text.strip():
            return
            
        print(f"🔊 Speaking: \"{text[:50]}...\"" if len(text) > 50 else f"🔊 Speaking: \"{text}\"")
        self._set_speaking(True)
        
        try:
            if self.tts_engine == "espeak":
                self._speak_espeak(text)
            elif self.tts_engine == "pyttsx3":
                self._speak_pyttsx3(text)
            elif self.tts_engine == "say":  # macOS
                self._speak_say(text)
            else:
                print(f"⚠️ Unknown TTS engine: {self.tts_engine}")
        finally:
            self._set_speaking(False)
    
    def _speak_espeak(self, text: str):
        """Use espeak for TTS (Linux)."""
        cmd = ["espeak", "-s", str(self.rate)]
        if self.voice:
            cmd.extend(["-v", self.voice])
        cmd.append(text)
        
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except FileNotFoundError:
            print("⚠️ espeak not found. Install with: sudo apt install espeak")
        except subprocess.CalledProcessError as e:
            print(f"⚠️ espeak error: {e}")
    
    def _speak_pyttsx3(self, text: str):
        """Use pyttsx3 for TTS (cross-platform)."""
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty('rate', self.rate)
            if self.voice:
                engine.setProperty('voice', self.voice)
            engine.say(text)
            engine.runAndWait()
        except ImportError:
            print("⚠️ pyttsx3 not found. Install with: pip install pyttsx3")
        except Exception as e:
            print(f"⚠️ pyttsx3 error: {e}")
    
    def _speak_say(self, text: str):
        """Use macOS say command."""
        cmd = ["say"]
        if self.voice:
            cmd.extend(["-v", self.voice])
        cmd.append(text)
        
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except FileNotFoundError:
            print("⚠️ say command not found (macOS only)")
        except subprocess.CalledProcessError as e:
            print(f"⚠️ say error: {e}")
    
    def play_file(self, audio_path: str):
        """Play an audio file through speakers."""
        path = Path(audio_path)
        if not path.exists():
            print(f"⚠️ Audio file not found: {audio_path}")
            return
        
        print(f"🔊 Playing: {path.name}")
        self._set_speaking(True)
        
        # Try different players
        players = [
            ["mpv", "--no-video", str(path)],
            ["ffplay", "-nodisp", "-autoexit", str(path)],
            ["aplay", str(path)],  # Linux
            ["afplay", str(path)],  # macOS
        ]
        
        try:
            for cmd in players:
                try:
                    subprocess.run(cmd, check=True, capture_output=True)
                    return
                except FileNotFoundError:
                    continue
                except subprocess.CalledProcessError:
                    continue
            
            print("⚠️ No audio player found. Install mpv or ffmpeg.")
        finally:
            self._set_speaking(False)
    
    def watch_queue(self):
        """Watch the TTS queue file and speak entries."""
        self._running = True
        self._queue_file.parent.mkdir(parents=True, exist_ok=True)
        
        print(f"👂 Watching TTS queue: {self._queue_file}")
        
        # Clear any existing queue on startup (avoid replay)
        if self._queue_file.exists():
            self._queue_file.unlink()
        
        while self._running:
            try:
                if self._queue_file.exists():
                    # Read and process all entries
                    with open(self._queue_file, 'r') as f:
                        lines = f.readlines()
                    
                    # Clear the file immediately
                    self._queue_file.unlink()
                    
                    for line in lines:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                            if entry.get("type") == "tts":
                                self.speak(entry.get("text", ""))
                            elif entry.get("type") == "audio":
                                self.play_file(entry.get("path", ""))
                        except json.JSONDecodeError:
                            # Plain text fallback
                            self.speak(line)
                
                time.sleep(0.1)  # Check frequently for responsiveness
                
            except Exception as e:
                print(f"⚠️ Queue watch error: {e}")
                time.sleep(1)
    
    def stop(self):
        """Stop watching the queue."""
        self._running = False


def queue_tts(text: str):
    """Add text to the TTS queue."""
    queue_file = Path.home() / ".clawdbot" / "ganglia-tts-queue.jsonl"
    queue_file.parent.mkdir(parents=True, exist_ok=True)
    
    entry = {"type": "tts", "text": text, "timestamp": time.time()}
    
    with open(queue_file, 'a') as f:
        f.write(json.dumps(entry) + '\n')


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        # Speak provided text
        text = " ".join(sys.argv[1:])
        speaker = Speaker()
        speaker.speak(text)
    else:
        # Watch queue
        speaker = Speaker()
        try:
            speaker.watch_queue()
        except KeyboardInterrupt:
            speaker.stop()
            print("\nStopped.")
