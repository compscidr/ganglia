"""
Clawdbot Response Handler for Ganglia.

Watches for text responses from Clawdbot and speaks them using local TTS.

## How it works

1. Clawdbot writes responses to ~/.clawdbot/ganglia-responses.jsonl (via SSH)
2. This handler watches the file for new entries
3. New responses are spoken using the configured TTS engine

## Response format (JSONL)

Each line is a JSON object:
    {"timestamp": 1234567890.123, "text": "Hello!", "voice": "default"}

## Usage

    from ganglia.integrations.response_handler import ResponseHandler
    from ganglia.tts import PiperTTS
    
    tts = PiperTTS(model="en_US-lessac-medium")
    handler = ResponseHandler(tts=tts)
    handler.start()  # Blocks, watching for responses
"""

import json
import time
import threading
from pathlib import Path
from typing import Optional, Callable
from dataclasses import dataclass

from ganglia.tts.base import TTSEngine


# Default response file location
DEFAULT_RESPONSE_FILE = Path.home() / ".clawdbot" / "ganglia-responses.jsonl"
LAST_READ_FILE = Path.home() / ".clawdbot" / "ganglia-responses-last-read"


@dataclass
class Response:
    """A response from Clawdbot."""
    timestamp: float
    text: str
    voice: str = "default"
    
    @classmethod
    def from_dict(cls, data: dict) -> "Response":
        return cls(
            timestamp=data.get("timestamp", time.time()),
            text=data.get("text", ""),
            voice=data.get("voice", "default"),
        )


class ResponseHandler:
    """
    Watches for Clawdbot responses and speaks them.
    
    Args:
        tts: TTS engine to use for speaking
        response_file: Path to response JSONL file
        poll_interval: Seconds between file checks
        on_response: Optional callback when response is received
    """
    
    def __init__(
        self,
        tts: TTSEngine,
        response_file: Optional[Path] = None,
        poll_interval: float = 0.5,
        on_response: Optional[Callable[[Response], None]] = None,
    ):
        self.tts = tts
        self.response_file = response_file or DEFAULT_RESPONSE_FILE
        self.poll_interval = poll_interval
        self.on_response = on_response
        
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_read_timestamp = self._load_last_read()
        
        # Ensure directory exists
        self.response_file.parent.mkdir(parents=True, exist_ok=True)
    
    def _load_last_read(self) -> float:
        """Load timestamp of last read response."""
        if LAST_READ_FILE.exists():
            try:
                return float(LAST_READ_FILE.read_text().strip())
            except (ValueError, OSError):
                pass
        return 0.0
    
    def _save_last_read(self, timestamp: float) -> None:
        """Save timestamp of last read response."""
        try:
            LAST_READ_FILE.write_text(str(timestamp))
        except OSError:
            pass
    
    def get_new_responses(self) -> list[Response]:
        """Get responses newer than last read timestamp."""
        if not self.response_file.exists():
            return []
        
        responses = []
        try:
            for line in self.response_file.read_text().strip().split("\n"):
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if data.get("timestamp", 0) > self._last_read_timestamp:
                        responses.append(Response.from_dict(data))
                except json.JSONDecodeError:
                    continue
        except OSError:
            pass
        
        return sorted(responses, key=lambda r: r.timestamp)
    
    def process_response(self, response: Response) -> None:
        """Process a single response - speak it."""
        if not response.text.strip():
            return
        
        print(f"🔊 Speaking: \"{response.text[:50]}{'...' if len(response.text) > 50 else ''}\"")
        
        # Call optional callback
        if self.on_response:
            self.on_response(response)
        
        # Speak the response
        try:
            self.tts.speak(response.text)
        except Exception as e:
            print(f"⚠️ TTS failed: {e}")
        
        # Update last read timestamp
        self._last_read_timestamp = response.timestamp
        self._save_last_read(response.timestamp)
    
    def poll_once(self) -> int:
        """Check for new responses and process them. Returns count processed."""
        responses = self.get_new_responses()
        for response in responses:
            self.process_response(response)
        return len(responses)
    
    def start(self, blocking: bool = True) -> None:
        """
        Start watching for responses.
        
        Args:
            blocking: If True, blocks the current thread. If False, runs in background.
        """
        self._running = True
        
        if blocking:
            self._watch_loop()
        else:
            self._thread = threading.Thread(target=self._watch_loop, daemon=True)
            self._thread.start()
    
    def stop(self) -> None:
        """Stop watching for responses."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
    
    def _watch_loop(self) -> None:
        """Main watch loop."""
        print(f"👂 Watching for responses in {self.response_file}")
        print(f"   TTS engine: {self.tts.name}")
        print(f"   Poll interval: {self.poll_interval}s")
        print(f"   Press Ctrl+C to stop\n")
        
        try:
            while self._running:
                self.poll_once()
                time.sleep(self.poll_interval)
        except KeyboardInterrupt:
            print("\n\n👋 Stopping response handler...")
            self._running = False


def create_response_handler(
    tts_engine: str = "piper",
    model: str = "en_US-lessac-medium",
    **tts_kwargs,
) -> ResponseHandler:
    """
    Create a response handler with the specified TTS engine.
    
    Args:
        tts_engine: TTS engine name ("piper" or "espeak")
        model: Model name/path for the TTS engine
        **tts_kwargs: Additional arguments for the TTS engine
    
    Returns:
        Configured ResponseHandler
    """
    if tts_engine == "piper":
        from ganglia.tts import PiperTTS
        tts = PiperTTS(model=model, **tts_kwargs)
    else:
        raise ValueError(f"Unknown TTS engine: {tts_engine}")
    
    return ResponseHandler(tts=tts)


# CLI entry point
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Watch for Clawdbot responses and speak them",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Basic usage with Piper
    python -m ganglia.integrations.response_handler --model en_US-lessac-medium
    
    # With custom model path
    python -m ganglia.integrations.response_handler --model /path/to/model.onnx
"""
    )
    parser.add_argument("--engine", default="piper", choices=["piper"],
                        help="TTS engine to use")
    parser.add_argument("--model", default="en_US-lessac-medium",
                        help="TTS model name or path")
    parser.add_argument("--poll-interval", type=float, default=0.5,
                        help="Seconds between file checks")
    
    args = parser.parse_args()
    
    handler = create_response_handler(
        tts_engine=args.engine,
        model=args.model,
    )
    handler.poll_interval = args.poll_interval
    handler.start(blocking=True)
