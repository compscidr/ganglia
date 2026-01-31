"""
Base TTS engine interface.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class TTSEngine(ABC):
    """Abstract base class for TTS engines."""
    
    @abstractmethod
    def speak(self, text: str) -> None:
        """Speak text immediately (blocking)."""
        pass
    
    @abstractmethod
    def synthesize(self, text: str, output_path: Path) -> Path:
        """Synthesize text to audio file."""
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Engine name for logging."""
        pass
