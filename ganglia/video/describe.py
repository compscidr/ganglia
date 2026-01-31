"""
Vision description module - sends frames to vision model for description.
"""

import subprocess
import json
import time
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from .capture import Frame


@dataclass
class VisionResult:
    """Result from vision model."""
    description: str
    timestamp: float
    model: str
    

def describe_frame_clawdbot(
    frame: Frame,
    prompt: str = "Describe what you see in this image briefly.",
    session_id: Optional[str] = None,
    channel: str = "discord",
    target: str = "channel:1465867928724439043",
    ssh_host: Optional[str] = None,
) -> Optional[VisionResult]:
    """
    Send a frame to the agent for analysis.
    
    Posts image to Discord, then triggers the agent to describe it.
    
    Args:
        ssh_host: If set, SCP frame to remote host and run commands via SSH
    """
    # Save frame to temp location (local)
    local_path = Path.home() / ".clawdbot" / "ganglia-frame.jpg"
    local_path.parent.mkdir(parents=True, exist_ok=True)
    frame.save(str(local_path))
    
    # For remote: SCP frame to Mac, use remote path for commands
    if ssh_host:
        remote_path = "~/.clawdbot/ganglia-frame.jpg"
        try:
            subprocess.run(
                ["scp", str(local_path), f"{ssh_host}:{remote_path}"],
                capture_output=True, timeout=30
            )
        except Exception as e:
            print(f"⚠️ Failed to SCP frame: {e}")
            return None
        temp_path = Path(remote_path.replace("~", ""))  # For command building
    else:
        temp_path = local_path
    
    def run_cmd(cmd, timeout=30):
        """Run command locally or via SSH."""
        if ssh_host:
            import shlex
            cmd_str = shlex.join(cmd)
            ssh_cmd = ["ssh", ssh_host, f"bash -lc {shlex.quote(cmd_str)}"]
            return subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=timeout)
        else:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    
    # Post image with prompt - will naturally appear in agent's session
    # For remote, use the path on the Mac
    media_path = "~/.clawdbot/ganglia-frame.jpg" if ssh_host else str(temp_path)
    
    # Include prompt in message so agent sees it with the image
    message = f"👁️ **[Vision]** {prompt}"
    
    post_cmd = [
        "clawdbot", "message", "send",
        "--channel", channel,
        "--target", target,
        "--message", message,
        "--media", media_path,
    ]
    
    try:
        result = run_cmd(post_cmd, timeout=30)
        if result.returncode != 0:
            print(f"⚠️ Failed to post image: {result.stderr}")
            return None
        
        return VisionResult(
            description="(sent to channel)",
            timestamp=time.time(),
            model="clawdbot"
        )
    except Exception as e:
        print(f"⚠️ Vision error: {e}")
        return None


def emit_vision_event(
    frame: Frame,
    description: str,
    output_file: Optional[str] = None
):
    """Emit a vision event to the events file."""
    event = {
        "type": "vision",
        "timestamp": frame.timestamp,
        "iso_time": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(frame.timestamp)),
        "source": "ganglia",
        "data": {
            "description": description,
            "width": frame.width,
            "height": frame.height,
            "device": frame.device,
        }
    }
    
    if output_file:
        with open(output_file, 'a') as f:
            f.write(json.dumps(event) + '\n')
    
    return event


if __name__ == "__main__":
    from .capture import capture_frame
    
    print("Capturing frame...")
    frame = capture_frame()
    
    if frame:
        print(f"Captured {frame.width}x{frame.height}")
        print("Sending to Clawdbot for description...")
        result = describe_frame_clawdbot(frame, "What do you see?")
        if result:
            print(f"Result: {result.description}")
    else:
        print("Failed to capture")
