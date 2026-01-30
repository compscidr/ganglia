"""
Clawdbot integration for ganglia.

Writes events to a file that Clawdbot can monitor,
or triggers wake events directly.
"""

import json
import os
from pathlib import Path
from typing import Optional
from datetime import datetime

from ganglia.events import Event


# Default location for ganglia events
DEFAULT_EVENTS_FILE = Path.home() / ".clawdbot" / "ganglia-events.jsonl"


class ClawdbotIntegration:
    """
    Integration with Clawdbot agent framework.
    
    Writes events to a JSONL file that Clawdbot can monitor
    during heartbeats or via cron jobs.
    """
    
    def __init__(
        self,
        events_file: Optional[Path] = None,
        max_events: int = 1000,  # Max events to keep in file
    ):
        self.events_file = events_file or DEFAULT_EVENTS_FILE
        self.max_events = max_events
        
        # Ensure directory exists
        self.events_file.parent.mkdir(parents=True, exist_ok=True)
        
    def write_event(self, event: Event):
        """Write an event to the events file."""
        with open(self.events_file, "a") as f:
            f.write(event.to_json() + "\n")
        
        # Trim file if too large
        self._trim_events_file()
    
    def _trim_events_file(self):
        """Keep only the last N events."""
        if not self.events_file.exists():
            return
            
        lines = self.events_file.read_text().strip().split("\n")
        if len(lines) > self.max_events:
            # Keep last max_events
            lines = lines[-self.max_events:]
            self.events_file.write_text("\n".join(lines) + "\n")
    
    def get_unread_events(self, since: Optional[float] = None) -> list:
        """
        Get events newer than the given timestamp.
        
        Args:
            since: Unix timestamp. If None, returns all events.
            
        Returns:
            List of event dicts
        """
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
        """
        Mark events as read by writing a marker file.
        
        Args:
            until_timestamp: Mark all events up to this time as read
        """
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


def create_clawdbot_handler(events_file: Optional[Path] = None):
    """
    Create an event handler that writes to Clawdbot's events file.
    
    Usage:
        emitter.add_handler(create_clawdbot_handler())
    """
    integration = ClawdbotIntegration(events_file)
    return integration.write_event


# CLI helper to read events (for testing)
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
