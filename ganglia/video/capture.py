"""
Camera capture module - captures frames from webcam.
"""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import base64
import io


@dataclass
class Frame:
    """A captured video frame with metadata."""
    image: bytes  # JPEG bytes
    width: int
    height: int
    timestamp: float
    device: int
    
    def to_base64(self) -> str:
        """Convert to base64 for API transmission."""
        return base64.b64encode(self.image).decode('utf-8')
    
    def to_data_url(self) -> str:
        """Convert to data URL for embedding."""
        b64 = self.to_base64()
        return f"data:image/jpeg;base64,{b64}"
    
    def save(self, path: str) -> str:
        """Save frame to file."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(self.image)
        return str(p)


class Camera:
    """
    Captures frames from a camera device.
    
    Uses OpenCV for cross-platform webcam access.
    """
    
    def __init__(
        self,
        device: int = 0,  # 0 = default webcam
        width: int = 1280,
        height: int = 720,
        warmup_frames: int = 5,  # Skip initial frames (auto-exposure settling)
    ):
        self.device = device
        self.width = width
        self.height = height
        self.warmup_frames = warmup_frames
        self._cap = None
    
    def _ensure_open(self):
        """Open camera if not already open."""
        if self._cap is None:
            import cv2
            self._cap = cv2.VideoCapture(self.device)
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            
            # Warmup - let auto-exposure settle
            for _ in range(self.warmup_frames):
                self._cap.read()
    
    def capture(self, quality: int = 85) -> Optional[Frame]:
        """
        Capture a single frame.
        
        Args:
            quality: JPEG quality (1-100)
            
        Returns:
            Frame object or None if capture failed
        """
        import cv2
        
        self._ensure_open()
        
        ret, frame = self._cap.read()
        if not ret:
            return None
        
        # Get actual dimensions
        height, width = frame.shape[:2]
        
        # Encode as JPEG
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, quality]
        _, jpeg = cv2.imencode('.jpg', frame, encode_params)
        
        return Frame(
            image=jpeg.tobytes(),
            width=width,
            height=height,
            timestamp=time.time(),
            device=self.device
        )
    
    def release(self):
        """Release camera resources."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.release()


def capture_frame(
    device: int = 0,
    width: int = 1280,
    height: int = 720,
    quality: int = 85
) -> Optional[Frame]:
    """
    Quick helper to capture a single frame.
    
    Opens camera, captures, closes. Use Camera class for multiple captures.
    """
    with Camera(device=device, width=width, height=height) as cam:
        return cam.capture(quality=quality)


def list_cameras() -> list[dict]:
    """List available camera devices."""
    import cv2
    
    cameras = []
    for i in range(10):  # Check first 10 indices
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cameras.append({
                "index": i,
                "width": width,
                "height": height,
            })
            cap.release()
    
    return cameras


if __name__ == "__main__":
    import sys
    
    if "--list" in sys.argv:
        print("Available cameras:")
        for cam in list_cameras():
            print(f"  [{cam['index']}] {cam['width']}x{cam['height']}")
    else:
        print("Capturing frame...")
        frame = capture_frame()
        if frame:
            path = frame.save("/tmp/ganglia-test.jpg")
            print(f"Saved to {path} ({frame.width}x{frame.height})")
        else:
            print("Failed to capture frame")
