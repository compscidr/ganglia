"""
Event emission for ganglia.
Structured events that can be consumed by agents, webhooks, or other systems.
"""

import json
import time
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, Callable, List
from enum import Enum
from datetime import datetime, timezone


class EventType(Enum):
    """Types of events ganglia can emit."""
    SPEECH = "speech"
    WAKE_WORD = "wake_word"
    SILENCE = "silence"
    NOISE = "noise"
    # Future: MOTION, PERSON, OBJECT, NOVELTY, etc.


@dataclass
class Event:
    """A ganglia event."""
    type: EventType
    timestamp: float
    data: Dict[str, Any]
    source: str = "ganglia"
    confidence: float = 1.0
    
    def to_dict(self) -> dict:
        return {
            "type": self.type.value,
            "timestamp": self.timestamp,
            "iso_time": datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat(),
            "source": self.source,
            "confidence": self.confidence,
            "data": self.data
        }
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict())


class EventEmitter:
    """
    Emits events to registered handlers.
    
    Handlers can be:
    - stdout (JSON lines)
    - file (append JSON lines)
    - callback functions
    - webhooks (future)
    """
    
    def __init__(self):
        self._handlers: List[Callable[[Event], None]] = []
        
    def add_handler(self, handler: Callable[[Event], None]):
        """Add an event handler."""
        self._handlers.append(handler)
        
    def add_stdout_handler(self):
        """Add handler that prints JSON to stdout."""
        def handler(event: Event):
            print(event.to_json(), flush=True)
        self._handlers.append(handler)
        
    def add_file_handler(self, path: str):
        """Add handler that appends JSON lines to a file."""
        def handler(event: Event):
            with open(path, "a") as f:
                f.write(event.to_json() + "\n")
        self._handlers.append(handler)
        
    def emit(self, event: Event):
        """Emit an event to all handlers."""
        for handler in self._handlers:
            try:
                handler(event)
            except Exception as e:
                print(f"Error in event handler: {e}")


# Convenience functions for creating events

def speech_event(
    text: str,
    language: str,
    duration: float,
    confidence: float = 1.0,
    segments: Optional[List[dict]] = None
) -> Event:
    """Create a speech transcription event."""
    return Event(
        type=EventType.SPEECH,
        timestamp=time.time(),
        confidence=confidence,
        data={
            "text": text,
            "language": language,
            "duration": duration,
            "segments": segments or []
        }
    )


def wake_word_event(
    word: str,
    confidence: float = 1.0
) -> Event:
    """Create a wake word detection event."""
    return Event(
        type=EventType.WAKE_WORD,
        timestamp=time.time(),
        confidence=confidence,
        data={"word": word}
    )


if __name__ == "__main__":
    # Test event emission
    emitter = EventEmitter()
    emitter.add_stdout_handler()
    
    # Emit a test event
    event = speech_event(
        text="Hello, this is a test",
        language="en",
        duration=2.5,
        confidence=0.95
    )
    
    emitter.emit(event)
