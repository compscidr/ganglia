"""
Text-to-speech engines for Ganglia.

Supports multiple TTS backends:
- Piper (recommended): Fast, high-quality, runs locally
- espeak: Lightweight fallback
"""

from .piper import PiperTTS
from .base import TTSEngine

__all__ = ["PiperTTS", "TTSEngine"]
