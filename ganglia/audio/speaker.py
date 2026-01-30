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
        """Use macOS say command with audio level feedback for face."""
        import tempfile
        import os
        import wave
        import struct
        import time
        import threading
        
        # Generate audio file first
        temp_file = tempfile.NamedTemporaryFile(suffix='.aiff', delete=False)
        temp_path = temp_file.name
        temp_file.close()
        
        level_file = Path.home() / ".clawdbot" / "ganglia-audio-level"
        
        try:
            # Generate speech to file
            cmd = ["say", "-o", temp_path]
            if self.voice:
                cmd.extend(["-v", self.voice])
            cmd.append(text)
            subprocess.run(cmd, check=True, capture_output=True)
            
            # Analyze audio and extract amplitude envelope
            try:
                # Convert to wav for easier analysis
                wav_path = temp_path + ".wav"
                subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16", temp_path, wav_path], 
                             capture_output=True)
                
                # Read wav and extract amplitudes
                with wave.open(wav_path, 'rb') as wf:
                    n_frames = wf.getnframes()
                    framerate = wf.getframerate()
                    raw = wf.readframes(n_frames)
                    samples = struct.unpack(f"<{n_frames}h", raw)
                    
                    # Calculate envelope (amplitude every 50ms)
                    chunk_size = framerate // 20  # 50ms chunks
                    envelope = []
                    for i in range(0, len(samples), chunk_size):
                        chunk = samples[i:i+chunk_size]
                        if chunk:
                            level = sum(abs(s) for s in chunk) / len(chunk) / 32768
                            envelope.append(min(1.0, level * 3))  # Normalize and boost
                    
                    duration = n_frames / framerate
                
                os.unlink(wav_path)
                
                # Play audio while updating level file
                def update_levels():
                    start = time.time()
                    idx = 0
                    while idx < len(envelope):
                        elapsed = time.time() - start
                        idx = int(elapsed * 20)  # 20 updates per second
                        if idx < len(envelope):
                            level_file.write_text(str(envelope[idx]))
                        time.sleep(0.04)
                    level_file.write_text("0")
                
                level_thread = threading.Thread(target=update_levels, daemon=True)
                level_thread.start()
                
                subprocess.run(["afplay", temp_path], check=True, capture_output=True)
                level_thread.join(timeout=1)
                
            except Exception as e:
                # Fallback to simple playback
                print(f"⚠️ Audio analysis failed: {e}, using simple playback")
                subprocess.run(["afplay", temp_path], check=True, capture_output=True)
                
        except FileNotFoundError:
            print("⚠️ say/afplay command not found (macOS only)")
        except Exception as e:
            print(f"⚠️ say error: {e}")
        finally:
            # Clean up
            try:
                os.unlink(temp_path)
            except:
                pass
            try:
                level_file.write_text("0")
            except:
                pass
    
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
