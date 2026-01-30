"""Video capture and processing for ganglia."""

from .capture import Camera, capture_frame, list_cameras
from .describe import describe_frame_clawdbot

__all__ = ["Camera", "capture_frame", "list_cameras", "describe_frame_clawdbot"]
