"""
Clawdbot integration for Ganglia.

Routes voice transcriptions to a Clawdbot agent session. Supports local and remote
(SSH) setups where Ganglia runs on one machine and Clawdbot on another.

## How it works

1. Ganglia detects speech and transcribes it
2. This integration sends the transcription to a Clawdbot session
3. The agent receives it as a voice message and can respond

## Session Discovery

The integration needs to know which Clawdbot session to send voice to. It does this
by querying `clawdbot sessions list` and finding a session matching your configured
channel (discord, telegram, etc.) and optionally a specific target (channel ID).

The session UUID is cached in `~/.clawdbot/ganglia-session-id` and refreshed
automatically if delivery fails or the file doesn't exist.

## Remote Setup (SSH)

When Ganglia runs on a different machine than Clawdbot (e.g., sensors on Ubuntu,
Clawdbot on Mac), set `ssh_host` to route commands via SSH:

    ssh_host="user@macbook.local"

This will:
- Run `clawdbot` commands on the remote host
- Write the session ID cache on the remote host
- Write events to the remote host's events file
"""

import json
import subprocess
import shlex
from pathlib import Path
from typing import Optional
from datetime import datetime

from ganglia.events import Event


# Default location for ganglia events (on the Clawdbot host)
DEFAULT_EVENTS_FILE = Path.home() / ".clawdbot" / "ganglia-events.jsonl"
SESSION_ID_FILE = Path.home() / ".clawdbot" / "ganglia-session-id"


class ClawdbotIntegration:
    """
    Integration with Clawdbot agent framework.
    
    Sends voice transcriptions to a Clawdbot session. Automatically discovers
    the correct session ID based on channel and target configuration.
    
    Args:
        channel: Target channel type ("discord", "telegram", "signal", etc.)
        target: Optional target within channel (e.g., "channel:1234567890" for Discord)
        ssh_host: SSH host where Clawdbot runs (e.g., "user@macbook.local")
                  Leave None if Clawdbot runs locally.
        events_file: Path to events file (for polling mode). Default: ~/.clawdbot/ganglia-events.jsonl
        max_events: Max events to keep in file (older ones are trimmed)
        reactive: If True, trigger agent immediately on speech events
        voice_prefix: Prefix for voice messages (default: "🎤 [Voice]")
        speaker_label: Optional speaker name (e.g., "Jason said:")
    
    Example - Local setup:
        integration = ClawdbotIntegration(
            channel="discord",
            target="channel:1234567890",
            reactive=True
        )
    
    Example - Remote setup (sensors on Ubuntu, Clawdbot on Mac):
        integration = ClawdbotIntegration(
            channel="discord",
            target="channel:1234567890",
            ssh_host="jason@macbook.local",
            reactive=True
        )
    """
    
    def __init__(
        self,
        channel: str = "discord",
        target: Optional[str] = None,
        ssh_host: Optional[str] = None,
        events_file: Optional[Path] = None,
        max_events: int = 1000,
        reactive: bool = False,
        voice_prefix: str = "🎤 [Voice]",
        speaker_label: Optional[str] = None,
    ):
        self.channel = channel
        self.target = target
        self.ssh_host = ssh_host
        self.events_file = events_file or DEFAULT_EVENTS_FILE
        self.max_events = max_events
        self.reactive = reactive
        self.voice_prefix = voice_prefix
        self.speaker_label = speaker_label
        
        # Cached session ID (discovered on first use)
        self._session_id: Optional[str] = None
        
        # Ensure directory exists (only if local)
        if not ssh_host:
            self.events_file.parent.mkdir(parents=True, exist_ok=True)
    
    def handle_event(self, event: Event):
        """
        Handle an incoming event.
        
        - Always writes to events file (for history/polling)
        - If reactive=True and event is speech, triggers the agent
        """
        # Always write to file for history
        self._write_event(event)
        
        # If reactive mode, trigger agent on speech events
        if self.reactive and event.type.value == "speech":
            self._trigger_agent(event)
    
    # -------------------------------------------------------------------------
    # Session Discovery
    # -------------------------------------------------------------------------
    
    def get_session_id(self, force_refresh: bool = False) -> Optional[str]:
        """
        Get the Clawdbot session ID for voice delivery.
        
        1. Returns cached ID if available (unless force_refresh)
        2. Tries to read from session ID file
        3. If not found, discovers by querying sessions list
        4. Caches the result for future calls
        
        Returns:
            Session UUID string, or None if discovery fails
        """
        # Return cached if available
        if self._session_id and not force_refresh:
            return self._session_id
        
        # Try reading from file first
        session_id = self._read_session_id_file()
        if session_id and not force_refresh:
            self._session_id = session_id
            return session_id
        
        # Discover session ID
        session_id = self._discover_session_id()
        if session_id:
            self._session_id = session_id
            self._write_session_id_file(session_id)
            print(f"✅ Discovered session ID: {session_id[:20]}...")
        else:
            print(f"⚠️ Could not discover session for channel={self.channel} target={self.target}")
        
        return session_id
    
    def _discover_session_id(self) -> Optional[str]:
        """
        Discover session ID by querying `clawdbot sessions list`.
        
        Finds a session matching:
        - channel type (discord, telegram, etc.)
        - target (if specified)
        
        Returns the session's UUID (sessionId field), not the key.
        """
        cmd = ["clawdbot", "sessions", "list", "--json"]
        
        try:
            result = self._run_command_sync(cmd)
            if result.returncode != 0:
                print(f"⚠️ sessions list failed: {result.stderr}")
                return None
            
            data = json.loads(result.stdout)
            sessions = data.get("sessions", [])
            
            # Find matching session
            for session in sessions:
                # Check channel matches
                if session.get("channel") != self.channel:
                    continue
                
                # Check target matches (if specified)
                if self.target:
                    delivery = session.get("deliveryContext", {})
                    session_target = delivery.get("to", "")
                    if self.target not in session_target and session_target not in self.target:
                        continue
                
                # Found it! Return the UUID, not the key
                session_id = session.get("sessionId")
                if session_id:
                    return session_id
            
            print(f"⚠️ No session found for channel={self.channel} target={self.target}")
            print(f"   Available sessions: {[s.get('key') for s in sessions]}")
            return None
            
        except json.JSONDecodeError as e:
            print(f"⚠️ Failed to parse sessions list: {e}")
            return None
        except Exception as e:
            print(f"⚠️ Failed to discover session: {e}")
            return None
    
    def _read_session_id_file(self) -> Optional[str]:
        """Read cached session ID from file (via SSH if remote)."""
        if self.ssh_host:
            try:
                result = subprocess.run(
                    ["ssh", self.ssh_host, "cat ~/.clawdbot/ganglia-session-id 2>/dev/null"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()
            except Exception:
                pass
        else:
            if SESSION_ID_FILE.exists():
                content = SESSION_ID_FILE.read_text().strip()
                if content:
                    return content
        return None
    
    def _write_session_id_file(self, session_id: str):
        """Write session ID to cache file (via SSH if remote)."""
        if self.ssh_host:
            try:
                cmd = f"echo {shlex.quote(session_id)} > ~/.clawdbot/ganglia-session-id"
                subprocess.run(["ssh", self.ssh_host, cmd], timeout=5, capture_output=True)
            except Exception as e:
                print(f"⚠️ Failed to write session ID via SSH: {e}")
        else:
            SESSION_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
            SESSION_ID_FILE.write_text(session_id)
    
    # -------------------------------------------------------------------------
    # Agent Triggering
    # -------------------------------------------------------------------------
    
    def _trigger_agent(self, event: Event):
        """
        Send voice transcription to the Clawdbot agent.
        
        Uses `clawdbot agent` with the discovered session ID to inject the
        voice message into the agent's conversation context.
        """
        text = event.data.get("text", "")
        if not text.strip():
            return
        
        # Get session ID (discovers if needed)
        session_id = self.get_session_id()
        if not session_id:
            print("⚠️ No session ID available, cannot trigger agent")
            return
        
        # Format the message
        if self.speaker_label:
            message = f'{self.voice_prefix} {self.speaker_label} "{text}"'
        else:
            message = f"{self.voice_prefix} {text}"
        
        # Build command
        cmd = [
            "clawdbot", "agent",
            "--message", message,
            "--session-id", session_id,
            "--channel", self.channel,
            "--deliver",
        ]
        
        if self.target:
            cmd.extend(["--reply-to", self.target])
        
        try:
            self._run_command_async(cmd)
            preview = text[:50] + "..." if len(text) > 50 else text
            mode = f"ssh:{self.ssh_host}" if self.ssh_host else "local"
            print(f"🎤 Triggered agent ({mode}): \"{preview}\"")
        except Exception as e:
            print(f"⚠️ Failed to trigger agent: {e}")
            # Refresh session ID on next attempt
            self._session_id = None
    
    # -------------------------------------------------------------------------
    # Event File Management
    # -------------------------------------------------------------------------
    
    def _write_event(self, event: Event):
        """Write event to the events file (for history/polling)."""
        event_json = event.to_json()
        
        if self.ssh_host:
            cmd = f"echo {shlex.quote(event_json)} >> ~/.clawdbot/ganglia-events.jsonl"
            try:
                subprocess.run(["ssh", self.ssh_host, cmd], timeout=5, capture_output=True)
            except Exception as e:
                print(f"⚠️ Failed to write event via SSH: {e}")
        else:
            with open(self.events_file, "a") as f:
                f.write(event_json + "\n")
            self._trim_events_file()
    
    def _trim_events_file(self):
        """Keep only the last N events in the file."""
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
        """Mark events as read up to the given timestamp."""
        marker_file = self.events_file.parent / "ganglia-last-read"
        marker_file.write_text(str(until_timestamp))
    
    def get_last_read_timestamp(self) -> Optional[float]:
        """Get the timestamp of the last read marker."""
        marker_file = self.events_file.parent / "ganglia-last-read"
        if marker_file.exists():
            try:
                return float(marker_file.read_text().strip())
            except ValueError:
                pass
        return None
    
    # -------------------------------------------------------------------------
    # Command Execution
    # -------------------------------------------------------------------------
    
    def _run_command_sync(self, cmd: list) -> subprocess.CompletedProcess:
        """Run a command and wait for result (via SSH if remote)."""
        if self.ssh_host:
            cmd_str = shlex.join(cmd)
            ssh_cmd = ["ssh", self.ssh_host, f"bash -lc {shlex.quote(cmd_str)}"]
            return subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=30)
        else:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    
    def _run_command_async(self, cmd: list):
        """Run a command without waiting (via SSH if remote)."""
        if self.ssh_host:
            cmd_str = shlex.join(cmd)
            ssh_cmd = ["ssh", self.ssh_host, f"bash -lc {shlex.quote(cmd_str)}"]
            return subprocess.Popen(ssh_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# -----------------------------------------------------------------------------
# Factory Function
# -----------------------------------------------------------------------------

def create_clawdbot_handler(
    channel: str = "discord",
    target: Optional[str] = None,
    ssh_host: Optional[str] = None,
    reactive: bool = False,
    speaker_label: Optional[str] = None,
):
    """
    Create an event handler for Clawdbot integration.
    
    Args:
        channel: Target channel type ("discord", "telegram", "signal", etc.)
        target: Optional target within channel (e.g., "channel:1234567890")
        ssh_host: SSH host where Clawdbot runs (None = local)
        reactive: If True, trigger agent immediately on speech
        speaker_label: Optional speaker label (e.g., "Jason said:")
    
    Returns:
        Event handler function for use with ganglia.EventEmitter
    
    Example - Local Discord:
        handler = create_clawdbot_handler(
            channel="discord",
            target="channel:1234567890",
            reactive=True
        )
        emitter.add_handler(handler)
    
    Example - Remote (Ganglia on Ubuntu, Clawdbot on Mac):
        handler = create_clawdbot_handler(
            channel="discord",
            target="channel:1234567890",
            ssh_host="jason@macbook.local",
            reactive=True,
            speaker_label="Jason said:"
        )
        emitter.add_handler(handler)
    """
    integration = ClawdbotIntegration(
        channel=channel,
        target=target,
        ssh_host=ssh_host,
        reactive=reactive,
        speaker_label=speaker_label,
    )
    return integration.handle_event


# -----------------------------------------------------------------------------
# CLI for reading events (polling mode)
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Read Ganglia events for Clawdbot (polling mode)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show all events
  python -m ganglia.integrations.clawdbot
  
  # Show unread events and mark them as read
  python -m ganglia.integrations.clawdbot --unread --mark-read
  
  # Show events since a specific timestamp
  python -m ganglia.integrations.clawdbot --since 1704067200
"""
    )
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


# -----------------------------------------------------------------------------
# Response Pushing (Clawdbot → Ganglia)
# -----------------------------------------------------------------------------

RESPONSE_FILE = Path.home() / ".clawdbot" / "ganglia-responses.jsonl"


def push_response(
    text: str,
    ssh_host: Optional[str] = None,
    voice: str = "default",
) -> bool:
    """
    Push a text response to Ganglia for TTS playback.
    
    This is called from the Clawdbot side to send responses back to Ganglia.
    Ganglia's ResponseHandler will pick up the response and speak it.
    
    Args:
        text: Text to speak
        ssh_host: SSH host where Ganglia runs (None = local)
        voice: Voice identifier (for future multi-voice support)
    
    Returns:
        True if successful, False otherwise
    
    Example (from Clawdbot):
        # Local Ganglia
        push_response("Hello, I heard you!")
        
        # Remote Ganglia
        push_response("Hello!", ssh_host="jason@ubuntu-beast.local")
    """
    import time
    
    response = {
        "timestamp": time.time(),
        "text": text,
        "voice": voice,
    }
    response_json = json.dumps(response)
    
    if ssh_host:
        # Write to remote Ganglia host
        cmd = f"echo {shlex.quote(response_json)} >> ~/.clawdbot/ganglia-responses.jsonl"
        try:
            result = subprocess.run(
                ["ssh", ssh_host, cmd],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                print(f"⚠️ Failed to push response via SSH: {result.stderr}")
                return False
            return True
        except Exception as e:
            print(f"⚠️ SSH error: {e}")
            return False
    else:
        # Write locally
        try:
            RESPONSE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(RESPONSE_FILE, "a") as f:
                f.write(response_json + "\n")
            return True
        except Exception as e:
            print(f"⚠️ Failed to write response: {e}")
            return False
