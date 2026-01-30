"""
Clawdbot integration for ganglia.

Option 1: Write events to a file (for polling)
Option 2: Trigger agent directly via `clawdbot agent` (reactive)
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Optional
from datetime import datetime

from ganglia.events import Event


# Default location for ganglia events
DEFAULT_EVENTS_FILE = Path.home() / ".clawdbot" / "ganglia-events.jsonl"


class ClawdbotIntegration:
    """
    Integration with Clawdbot agent framework.
    
    Can either:
    1. Write events to a JSONL file for polling
    2. Directly trigger agent turns via CLI (reactive)
    """
    
    def __init__(
        self,
        events_file: Optional[Path] = None,
        max_events: int = 1000,
        reactive: bool = False,
        channel: str = "discord",
        reply_to: Optional[str] = None,  # e.g., "channel:1234567890"
    ):
        self.events_file = events_file or DEFAULT_EVENTS_FILE
        self.max_events = max_events
        self.reactive = reactive
        self.channel = channel
        self.reply_to = reply_to
        
        # Ensure directory exists
        self.events_file.parent.mkdir(parents=True, exist_ok=True)
    
    def handle_event(self, event: Event):
        """Handle an event - either write to file or trigger agent."""
        # Always write to file for history
        self._write_event(event)
        
        # If reactive mode, also trigger agent
        if self.reactive and event.type.value == "speech":
            self._trigger_agent(event)
    
    def _write_event(self, event: Event):
        """Write an event to the events file."""
        with open(self.events_file, "a") as f:
            f.write(event.to_json() + "\n")
        self._trim_events_file()
    
    def _trigger_agent(self, event: Event):
        """Trigger Clawdbot agent with the speech event."""
        text = event.data.get("text", "")
        if not text.strip():
            return
        
        # Format the message for the agent
        message = f"[Ganglia Audio] I heard you say: \"{text}\""
        
        # Build the clawdbot command
        cmd = [
            "clawdbot", "agent",
            "--agent", "main",
            "--message", message,
            "--channel", self.channel,
            "--deliver",
        ]
        
        if self.reply_to:
            cmd.extend(["--reply-to", self.reply_to])
        
        try:
            # Run async so we don't block the listener
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print(f"🤖 Triggered Clawdbot agent with: \"{text[:50]}...\"" if len(text) > 50 else f"🤖 Triggered Clawdbot agent with: \"{text}\"")
        except Exception as e:
            print(f"⚠️ Failed to trigger agent: {e}")
    
    def _trim_events_file(self):
        """Keep only the last N events."""
        if not self.events_file.exists():
            return
        
        try:
            lines = self.events_file.read_text().strip().split("\n")
            if len(lines) > self.max_events:
                lines = lines[-self.max_events:]
                self.events_file.write_text("\n".join(lines) + "\n")
        except Exception:
            pass
    
    def get_unread_events(self, since: Optional[float] = None) -> list:
        """Get events newer than the given timestamp."""
        if not self.events_file.exists():
            return []
        
        events = []
        for line in self.events_file.read_text().strip().split("\n"):
            if not line:
                continue
            try:
                event = json.loads(line)
                if since is None or event.get("timestamp", 0) > since:
                    events.append(event)
            except json.JSONDecodeError:
                continue
        
        return events
    
    def mark_read(self, until_timestamp: float):
        """Mark events as read."""
        marker_file = self.events_file.parent / "ganglia-last-read"
        marker_file.write_text(str(until_timestamp))
    
    def get_last_read_timestamp(self) -> Optional[float]:
        """Get the timestamp of the last read event."""
        marker_file = self.events_file.parent / "ganglia-last-read"
        if marker_file.exists():
            try:
                return float(marker_file.read_text().strip())
            except ValueError:
                pass
        return None


def create_clawdbot_handler(
    reactive: bool = False,
    channel: str = "discord", 
    reply_to: Optional[str] = None
):
    """
    Create an event handler for Clawdbot.
    
    Args:
        reactive: If True, trigger agent immediately on speech events
        channel: Delivery channel (discord, telegram, etc.)
        reply_to: Target for replies (e.g., "channel:1234567890")
    
    Usage:
        # Polling mode (write to file)
        emitter.add_handler(create_clawdbot_handler())
        
        # Reactive mode (trigger agent immediately)  
        emitter.add_handler(create_clawdbot_handler(
            reactive=True,
            channel="discord",
            reply_to="channel:1465867928724439043"
        ))
    """
    integration = ClawdbotIntegration(
        reactive=reactive,
        channel=channel,
        reply_to=reply_to
    )
    return integration.handle_event


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Read ganglia events for Clawdbot")
    parser.add_argument("--since", type=float, help="Only show events after this timestamp")
    parser.add_argument("--unread", action="store_true", help="Only show unread events")
    parser.add_argument("--mark-read", action="store_true", help="Mark shown events as read")
    args = parser.parse_args()
    
    integration = ClawdbotIntegration()
    
    since = args.since
    if args.unread:
        since = integration.get_last_read_timestamp()
    
    events = integration.get_unread_events(since)
    
    if events:
        for event in events:
            print(json.dumps(event))
        
        if args.mark_read:
            latest = max(e.get("timestamp", 0) for e in events)
            integration.mark_read(latest)
            print(f"\nMarked {len(events)} events as read", file=__import__('sys').stderr)
    else:
        print("No new events", file=__import__('sys').stderr)
