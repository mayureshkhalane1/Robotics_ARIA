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


def prepare_vision_frame(frame_bgr: np.ndarray, target_max_dim: int = 640) -> np.ndarray:
    """Resize a sampled frame for downstream vision models.

    The UI still streams live video, but detector/VLM sampling works better
    when the sampled frame is normalized to a consistent max dimension.
    """
    if frame_bgr is None or getattr(frame_bgr, "size", 0) == 0:
        return frame_bgr
    if target_max_dim <= 0:
        return frame_bgr
    h, w = frame_bgr.shape[:2]
    if h <= 0 or w <= 0:
        return frame_bgr
    max_dim = max(h, w)
    if max_dim == target_max_dim:
        return frame_bgr
    scale = float(target_max_dim) / float(max_dim)
    if scale == 1.0:
        return frame_bgr
    interp = cv2.INTER_CUBIC if scale > 1.0 else cv2.INTER_AREA
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    return cv2.resize(frame_bgr, (new_w, new_h), interpolation=interp)


class CameraManager:
    """Manages Webots camera frames and streaming."""

    def __init__(self, include_camera: bool = True):
        """Initialize camera manager.

        Args:
            include_camera: Whether to request camera data from the Webots bridge
        """
        self.include_camera = include_camera
        self.last_frame: Optional[Frame] = None
        self.last_update_time = 0.0
        self.frame_count = 0
        self.fps = 0.0

    def get_frame(self, refresh: bool = False) -> Optional[np.ndarray]:
        """Get latest camera frame as numpy array.

        Args:
            refresh: If True, always fetch a fresh frame from Webots first.

        Returns:
            BGR numpy array (HxWx3, uint8) or None if unavailable
        """
        if refresh or self.last_frame is None:
            self._fetch_frame()
        return self.last_frame.data if self.last_frame else None

    def update_frame(self, frame_bgr: np.ndarray) -> None:
        """Set the current frame from an externally-provided BGR numpy array.

        Used by the aria_agent to push frames without re-fetching from Webots.

        Args:
            frame_bgr: BGR numpy array (HxWx3, uint8)
        """
        now = time.time()
        metadata = FrameMetadata(
            timestamp=now,
            resolution=(frame_bgr.shape[0], frame_bgr.shape[1]),
        )
        self.last_frame = Frame(data=frame_bgr, metadata=metadata)
        self.frame_count += 1

    def get_frame_with_metadata(self) -> Optional[Frame]:
        """Get latest frame with metadata including pose.

        Returns:
            Frame object with data, metadata, and pose or None
        """
        if self.last_frame is None:
            self._fetch_frame()
        return self.last_frame

    def _fetch_frame(self) -> bool:
        """Fetch frame from the Webots bridge.

        Returns:
            True if successful, False otherwise
        """
        try:
            # Get robot state with camera enabled
            result = call_tool(
                "get_state",
                {"include_camera": True},
            )

            if not isinstance(result, dict) or result.get("error") or not result.get("success", False):
                message = result.get("message") if isinstance(result, dict) else str(result)
                print(f"[Camera] get_state failed: {message or 'unknown error'}")
                return False

            # Extract camera data
            state = result.get("state") or {}
            camera_data = state.get("camera") if isinstance(state, dict) else None

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
                try:
                    frame_bgra = np.frombuffer(image_bytes, dtype=np.uint8).reshape((height, width, 4))
                    # Convert BGRA to BGR (drop alpha channel)
                    frame_bgr = frame_bgra[:, :, :3].copy()  # Make copy to ensure contiguous
                except Exception as e:
                    print(f"[Camera] BGRA reshape failed: {e}. Trying JPEG fallback.")
                    # Fallback: try to decode as JPEG
                    nparr = np.frombuffer(image_bytes, np.uint8)
                    frame_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            elif encoding == "jpeg_base64" or encoding.endswith("jpeg"):
                # JPEG-encoded data
                nparr = np.frombuffer(image_bytes, np.uint8)
                frame_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            else:
                # Fallback: try to decode as image
                nparr = np.frombuffer(image_bytes, np.uint8)
                frame_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if frame_bgr is None or frame_bgr.size == 0:
                print(f"[Camera] Failed to decode image (encoding={encoding}, size={len(image_bytes)})")
                return False
            
            # Validate frame channels (after BGRA→BGR conversion, should be 3)
            if frame_bgr.shape[2] != 3:
                print(f"[Camera] Invalid frame channels: {frame_bgr.shape[2]} (expected 3)")
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

        frame = prepare_vision_frame(frame)
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