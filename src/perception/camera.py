"""Real-time camera manager for Webots robot."""

from __future__ import annotations

import base64
import io
import time
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

from src.mcp_server.server import call_tool


@dataclass
class FrameMetadata:
    """Metadata for a camera frame."""

    timestamp: float
    camera_id: str = "webots_camera_0"
    resolution: tuple[int, int] = (240, 320)  # height, width
    brightness: float = 0.0
    exposure_time: float = 0.033  # 30ms default
    focal_length: float = 1.0


@dataclass
class Frame:
    """A camera frame with metadata."""

    data: np.ndarray  # BGR format, shape HxWx3, uint8
    metadata: FrameMetadata
    pose: Optional[dict] = None  # {x, y, z, rotation}


class CameraManager:
    """Manages Webots camera frames and streaming."""

    def __init__(self, include_camera: bool = True):
        """Initialize camera manager.

        Args:
            include_camera: Whether to request camera data from MCP server
        """
        self.include_camera = include_camera
        self.last_frame: Optional[Frame] = None
        self.last_update_time = 0.0
        self.frame_count = 0
        self.fps = 0.0

    def get_frame(self) -> Optional[np.ndarray]:
        """Get latest camera frame as numpy array.

        Returns:
            BGR numpy array (HxWx3, uint8) or None if unavailable
        """
        if self.last_frame is None:
            self._fetch_frame()
        return self.last_frame.data if self.last_frame else None

    def get_frame_with_metadata(self) -> Optional[Frame]:
        """Get latest frame with metadata including pose.

        Returns:
            Frame object with data, metadata, and pose or None
        """
        if self.last_frame is None:
            self._fetch_frame()
        return self.last_frame

    def _fetch_frame(self) -> bool:
        """Fetch frame from MCP server.

        Returns:
            True if successful, False otherwise
        """
        try:
            # Get robot state with camera enabled
            result = call_tool(
                "get_state",
                {"include_camera": True},
            )

            if result.get("error"):
                print(f"[Camera] Error: {result.get('error')}")
                return False

            # Extract camera data
            state = result.get("state", {})
            camera_data = state.get("camera")

            if not camera_data:
                print("[Camera] No camera data in response")
                return False

            # Decode frame based on encoding
            encoding = camera_data.get("encoding", "bgra8_base64")
            image_base64 = camera_data.get("data")
            width = camera_data.get("width", 320)
            height = camera_data.get("height", 240)

            if not image_base64:
                print("[Camera] No image data in camera response")
                return False

            # Decode base64 to raw bytes
            image_bytes = base64.b64decode(image_base64)

            if encoding == "bgra8_base64":
                # BGRA format: 4 bytes per pixel
                frame_bgra = np.frombuffer(image_bytes, dtype=np.uint8).reshape((height, width, 4))
                # Convert BGRA to BGR (drop alpha channel)
                frame_bgr = frame_bgra[:, :, :3]
            else:
                # Fallback: try to decode as image
                nparr = np.frombuffer(image_bytes, np.uint8)
                frame_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if frame_bgr is None:
                print("[Camera] Failed to decode image")
                return False

            # Extract metadata
            now = time.time()
            metadata = FrameMetadata(
                timestamp=now,
                resolution=(frame_bgr.shape[0], frame_bgr.shape[1]),
            )

            # Extract pose
            pose = state.get("pose")

            # Update frame
            self.last_frame = Frame(data=frame_bgr, metadata=metadata, pose=pose)

            # Update FPS
            self.frame_count += 1
            if self.frame_count % 10 == 0:
                elapsed = now - self.last_update_time
                if elapsed > 0:
                    self.fps = 10.0 / elapsed
                self.last_update_time = now

            return True

        except Exception as e:
            print(f"[Camera] Exception: {e}")
            return False

    def get_camera_info(self) -> dict:
        """Get camera information.

        Returns:
            Dict with camera specs
        """
        if self.last_frame is None:
            self._fetch_frame()

        if self.last_frame:
            h, w = self.last_frame.metadata.resolution
            return {
                "resolution": (h, w),
                "fps": self.fps,
                "camera_id": self.last_frame.metadata.camera_id,
                "frame_count": self.frame_count,
            }
        return {"error": "No camera data available"}

    def encode_frame_jpeg(self, quality: int = 85) -> Optional[str]:
        """Encode current frame as JPEG and return base64 string.

        Args:
            quality: JPEG quality (0-100)

        Returns:
            Base64-encoded JPEG string or None
        """
        if self.last_frame is None:
            self._fetch_frame()

        if self.last_frame is None:
            return None

        try:
            # Encode to JPEG
            success, encoded = cv2.imencode(
                ".jpg", self.last_frame.data, [cv2.IMWRITE_JPEG_QUALITY, quality]
            )

            if not success:
                return None

            # Convert to base64
            jpeg_bytes = encoded.tobytes()
            return base64.b64encode(jpeg_bytes).decode("utf-8")

        except Exception as e:
            print(f"[Camera] Encoding error: {e}")
            return None

    def get_frame_for_detection(self) -> Optional[np.ndarray]:
        """Get frame optimized for object detection.

        Returns processed frame suitable for YOLO detection.
        """
        frame = self.get_frame()
        if frame is None:
            return None

        # Convert BGR to RGB for detection models
        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    def reset_stats(self) -> None:
        """Reset FPS counter and frame count."""
        self.frame_count = 0
        self.fps = 0.0
        self.last_update_time = time.time()


# Global camera manager instance
_camera_manager: Optional[CameraManager] = None


def get_camera_manager() -> CameraManager:
    """Get or create global camera manager.

    Returns:
        CameraManager instance
    """
    global _camera_manager
    if _camera_manager is None:
        _camera_manager = CameraManager(include_camera=True)
    return _camera_manager


def init_camera(include_camera: bool = True) -> CameraManager:
    """Initialize camera manager.

    Args:
        include_camera: Whether to request camera data

    Returns:
        CameraManager instance
    """
    global _camera_manager
    _camera_manager = CameraManager(include_camera=include_camera)
    return _camera_manager
