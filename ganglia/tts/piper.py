"""
Piper TTS engine for Ganglia.

Piper is a fast, local neural TTS system.
https://github.com/rhasspy/piper

Installation:
    pip install piper-tts

Or download binary:
    # Download from https://github.com/rhasspy/piper/releases
    wget https://github.com/rhasspy/piper/releases/download/v1.2.0/piper_amd64.tar.gz
    tar -xzf piper_amd64.tar.gz
    
Models:
    # Download a voice model (e.g., lessac for English)
    wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx
    wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json
"""

import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import Optional

from .base import TTSEngine


class PiperTTS(TTSEngine):
    """
    Piper TTS engine.
    
    Args:
        model: Path to .onnx model file, or model name if using piper-tts package
        piper_path: Path to piper binary (if not using pip package)
        speaker: Speaker ID for multi-speaker models
        length_scale: Speech speed (1.0 = normal, <1 = faster, >1 = slower)
    
    Example:
        tts = PiperTTS(model="en_US-lessac-medium")
        tts.speak("Hello world")
    """
    
    def __init__(
        self,
        model: str = "en_US-lessac-medium",
        piper_path: Optional[str] = None,
        speaker: Optional[int] = None,
        length_scale: float = 1.0,
    ):
        self.model = model
        self.piper_path = piper_path or self._find_piper()
        self.speaker = speaker
        self.length_scale = length_scale
        
        if not self.piper_path:
            raise RuntimeError(
                "Piper not found. Install with: pip install piper-tts\n"
                "Or download from: https://github.com/rhasspy/piper/releases"
            )
    
    def _find_piper(self) -> Optional[str]:
        """Find piper executable."""
        # Check if piper-tts Python package is installed
        try:
            import piper
            return "piper"  # Will use Python module
        except ImportError:
            pass
        
        # Check for binary in PATH
        piper_bin = shutil.which("piper")
        if piper_bin:
            return piper_bin
        
        # Check common locations
        common_paths = [
            Path.home() / ".local" / "bin" / "piper",
            Path("/usr/local/bin/piper"),
            Path("/opt/piper/piper"),
        ]
        for p in common_paths:
            if p.exists():
                return str(p)
        
        return None
    
    @property
    def name(self) -> str:
        return "piper"
    
    def speak(self, text: str) -> None:
        """Speak text immediately using aplay/paplay."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            output_path = Path(f.name)
        
        try:
            self.synthesize(text, output_path)
            self._play_audio(output_path)
        finally:
            output_path.unlink(missing_ok=True)
    
    def synthesize(self, text: str, output_path: Path) -> Path:
        """Synthesize text to WAV file."""
        # Try Python piper-tts first
        try:
            return self._synthesize_python(text, output_path)
        except ImportError:
            pass
        
        # Fall back to CLI
        return self._synthesize_cli(text, output_path)
    
    def _synthesize_python(self, text: str, output_path: Path) -> Path:
        """Synthesize using piper-tts Python package."""
        import wave
        from piper import PiperVoice
        
        voice = PiperVoice.load(self.model)
        
        with wave.open(str(output_path), "wb") as wav_file:
            # Must set up wave params before piper writes to it
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(voice.config.sample_rate)
            # synthesize returns chunks - write each one
            for audio_chunk in voice.synthesize(text):
                wav_file.writeframes(audio_chunk.audio_bytes)
        
        return output_path
    
    def _synthesize_cli(self, text: str, output_path: Path) -> Path:
        """Synthesize using piper CLI."""
        cmd = [
            self.piper_path,
            "--model", self.model,
            "--output_file", str(output_path),
        ]
        
        if self.speaker is not None:
            cmd.extend(["--speaker", str(self.speaker)])
        
        if self.length_scale != 1.0:
            cmd.extend(["--length_scale", str(self.length_scale)])
        
        result = subprocess.run(
            cmd,
            input=text,
            text=True,
            capture_output=True,
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"Piper failed: {result.stderr}")
        
        return output_path
    
    def _play_audio(self, audio_path: Path) -> None:
        """Play audio file using available player."""
        # Try common Linux audio players
        players = [
            ["paplay", str(audio_path)],  # PulseAudio
            ["aplay", str(audio_path)],   # ALSA
            ["play", str(audio_path)],    # SoX
        ]
        
        for cmd in players:
            if shutil.which(cmd[0]):
                subprocess.run(cmd, capture_output=True)
                return
        
        raise RuntimeError("No audio player found. Install pulseaudio, alsa-utils, or sox.")
