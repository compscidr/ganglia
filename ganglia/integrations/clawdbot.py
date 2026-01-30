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
    
    Supports SSH for remote sensor setups (e.g., sensors on Ubuntu, Clawdbot on Mac).
    """
    
    def __init__(
        self,
        events_file: Optional[Path] = None,
        max_events: int = 1000,
        reactive: bool = False,
        channel: str = "discord",
        reply_to: Optional[str] = None,  # e.g., "channel:1234567890"
        ssh_host: Optional[str] = None,  # e.g., "jason@macbook.local"
        webhook_url: Optional[str] = None,  # Discord webhook URL for posting voice as "user"
    ):
        self.events_file = events_file or DEFAULT_EVENTS_FILE
        self.max_events = max_events
        self.reactive = reactive
        self.channel = channel
        self.reply_to = reply_to
        self.ssh_host = ssh_host
        self.webhook_url = webhook_url
        
        # Ensure directory exists (only if local)
        if not ssh_host:
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
    
    def _run_command(self, cmd: list):
        """Run a command locally or via SSH."""
        if self.ssh_host:
            import shlex
            # Build command string and run via SSH
            cmd_str = shlex.join(cmd)
            ssh_cmd = ["ssh", self.ssh_host, f"bash -lc {shlex.quote(cmd_str)}"]
            return subprocess.Popen(ssh_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    def _trigger_agent(self, event: Event):
        """Post voice input via Discord webhook (appears as user message, triggers agent naturally)."""
        text = event.data.get("text", "")
        if not text.strip():
            return
        
        # If webhook URL is configured, post there (best approach - appears as user message)
        if self.webhook_url:
            self._post_to_webhook(text)
        else:
            # Fallback: write to shared events file and hope agent checks it
            self._write_shared_event(text)
            print(f"⚠️ No webhook configured - wrote to shared events (agent may not see immediately)")
    
    def _post_to_webhook(self, text: str):
        """Post to Discord webhook - appears as different user, triggers agent naturally."""
        import urllib.request
        import json
        
        payload = {
            "username": "🎤 Voice Input",
            "content": text,
        }
        
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            self.webhook_url,
            data=data,
            headers={'Content-Type': 'application/json'}
        )
        
        try:
            urllib.request.urlopen(req, timeout=10)
            preview = text[:50] + "..." if len(text) > 50 else text
            print(f"🎤 Posted to webhook: \"{preview}\"")
        except Exception as e:
            print(f"⚠️ Webhook failed: {e}")
    
    def _write_shared_event(self, text: str):
        """Write to shared events file as fallback."""
        shared_events_file = Path.home() / "clawd" / "memory" / "shared" / "events.jsonl"
        if shared_events_file.parent.exists():
            import json
            from datetime import datetime
            shared_event = {
                "ts": datetime.utcnow().isoformat() + "Z",
                "source": "ganglia:voice", 
                "type": "voice_input",
                "summary": f"🎤 Voice: {text}",
                "details": {"text": text}
            }
            try:
                with open(shared_events_file, "a") as f:
                    f.write(json.dumps(shared_event) + "\n")
            except Exception:
                pass
    
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
    reply_to: Optional[str] = None,
    ssh_host: Optional[str] = None,
    webhook_url: Optional[str] = None
):
    """
    Create an event handler for Clawdbot.
    
    Args:
        reactive: If True, trigger agent immediately on speech events
        channel: Delivery channel (discord, telegram, etc.)
        reply_to: Target for replies (e.g., "channel:1234567890")
        ssh_host: SSH host for remote clawdbot (e.g., "jason@macbook.local") [DEPRECATED]
        webhook_url: Discord webhook URL - posts voice as "user message" which triggers agent naturally
    
    Usage:
        # Polling mode (write to file only)
        emitter.add_handler(create_clawdbot_handler())
        
        # Webhook mode (RECOMMENDED - voice appears as user message, triggers agent)  
        emitter.add_handler(create_clawdbot_handler(
            reactive=True,
            webhook_url="https://discord.com/api/webhooks/..."
        ))
    """
    integration = ClawdbotIntegration(
        reactive=reactive,
        channel=channel,
        reply_to=reply_to,
        ssh_host=ssh_host,
        webhook_url=webhook_url
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
