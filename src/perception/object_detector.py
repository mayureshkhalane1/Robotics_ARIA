"""YOLO-based object detector for robot perception."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np
from ultralytics import YOLO


# Common COCO class aliases. The detector still returns every class supported by
# the loaded YOLO model via self.model.names, not only these household classes.
COCO_CLASSES = {
    39: "bottle",
    41: "cup",
    42: "fork",
    43: "knife",
    44: "spoon",
    47: "cup",
    48: "chair",
    49: "couch",
    50: "potted plant",
    51: "bed",
    52: "dining table",
    53: "toilet",
    54: "tv",
    55: "laptop",
    56: "mouse",
    57: "remote",
    58: "keyboard",
    59: "microwave",
    60: "oven",
    61: "toaster",
    62: "sink",
    63: "refrigerator",
}

# Extended mapping for common household items
READABLE_NAMES = {
    "bottle": "bottle",
    "cup": "cup",
    "fork": "fork",
    "knife": "knife",
    "spoon": "spoon",
    "chair": "chair",
    "couch": "couch",
    "potted plant": "plant",
    "bed": "bed",
    "dining table": "table",
    "toilet": "toilet",
    "tv": "monitor",
    "laptop": "laptop",
    "mouse": "mouse",
    "remote": "remote",
    "keyboard": "keyboard",
    "microwave": "microwave",
    "oven": "oven",
    "toaster": "toaster",
    "sink": "sink",
    "refrigerator": "fridge",
}


@dataclass
class Detection:
    """Single object detection."""

    class_name: str
    confidence: float
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 in pixels
    center: tuple[float, float]  # centroid in pixels
    class_id: int


class ObjectDetector:
    """YOLO-based object detector for robot perception."""

    def __init__(self, model_name: str = "yolo11m", confidence_threshold: float = 0.5, iou_threshold: float = 0.45):
        """Initialize object detector.

        Args:
            model_name: YOLO model name (yolo11m, yolo11s, etc.)
            confidence_threshold: Minimum confidence to keep detections (0.0-1.0)
            iou_threshold: NMS IoU threshold for duplicate suppression (0.0-1.0)
        """
        self.model_name = model_name
        self.confidence_threshold = confidence_threshold
        self.iou_threshold = iou_threshold
        # Open-vocabulary models (YOLO-World) detect arbitrary text-named classes
        # (e.g. "duck", "wooden box") instead of only the 80 fixed COCO classes.
        self.is_open_vocab = "world" in model_name.lower()

        # Load model (auto-downloads on first use)
        try:
            self.model = YOLO(f"{model_name}.pt")
            print(f"[Detector] Loaded {model_name} successfully "
                  f"(conf={confidence_threshold}, iou={iou_threshold}, "
                  f"open_vocab={self.is_open_vocab})")
        except Exception as e:
            print(f"[Detector] Failed to load model: {e}")
            self.model = None

    def set_classes(self, names) -> None:
        """For open-vocabulary (YOLO-World) models, set the text classes to look
        for.  No-op for standard COCO models (their classes are fixed)."""
        if not self.is_open_vocab or self.model is None:
            return
        try:
            self.model.set_classes(list(names))
            print(f"[Detector] Open-vocab classes set: {list(names)}")
        except Exception as e:
            print(f"[Detector] set_classes failed: {e}")

    def detect(
        self,
        frame: np.ndarray,
        confidence_threshold: Optional[float] = None,
    ) -> list[Detection]:
        """Detect objects in frame.

        Args:
            frame: BGR numpy array (HxWx3, uint8). YOLO expects BGR input!
            confidence_threshold: Optional per-call confidence override.

        Returns:
            List of Detection objects sorted by confidence (highest first)
        """
        if self.model is None:
            print("[Detector] Model not loaded")
            return []

        if frame is None or frame.size == 0:
            print("[Detector] Invalid frame: empty or None")
            return []

        if len(frame.shape) != 3 or frame.shape[2] != 3:
            print(f"[Detector] Invalid frame shape: {frame.shape} (expected HxWx3)")
            return []

        try:
            conf_threshold = (
                self.confidence_threshold
                if confidence_threshold is None
                else float(confidence_threshold)
            )
            # Run inference with explicit NMS
            results = self.model(
                frame,
                verbose=False,
                conf=conf_threshold,
                iou=self.iou_threshold  # Non-maximum suppression threshold
            )

            detections = []
            frame_h, frame_w = frame.shape[:2]

            # Process results
            if results and len(results) > 0:
                result = results[0]

                # Extract boxes
                if result.boxes is not None:
                    for box in result.boxes:
                        # Get box coordinates in pixels
                        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                        confidence = float(box.conf[0].cpu().numpy())
                        class_id = int(box.cls[0].cpu().numpy())

                        # Validate bbox bounds
                        if not (0 <= x1 < x2 <= frame_w and 0 <= y1 < y2 <= frame_h):
                            print(f"[Detector] Invalid bbox: ({x1:.1f},{y1:.1f},{x2:.1f},{y2:.1f}) outside frame {frame_w}x{frame_h}")
                            continue

                        # Validate confidence range
                        if not (0 <= confidence <= 1.0):
                            print(f"[Detector] Invalid confidence: {confidence} (must be 0-1)")
                            continue

                        # Get class name
                        class_name = self.model.names.get(class_id, f"object_{class_id}")
                        class_name = READABLE_NAMES.get(class_name, class_name)

                        # Calculate center
                        cx = (x1 + x2) / 2
                        cy = (y1 + y2) / 2

                        detection = Detection(
                            class_name=class_name,
                            confidence=confidence,
                            bbox=(x1, y1, x2, y2),
                            center=(cx, cy),
                            class_id=class_id,
                        )

                        detections.append(detection)

            # Sort by confidence descending
            detections.sort(key=lambda d: d.confidence, reverse=True)

            return detections

        except Exception as e:
            print(f"[Detector] Inference error: {e}")
            import traceback
            traceback.print_exc()
            return []

    def find_target(self, frame: np.ndarray, target_name: str) -> Optional[Detection]:
        """Find specific object in frame.

        Args:
            frame: RGB numpy array
            target_name: Name of object to find (e.g., "cup", "chair")

        Returns:
            Detection of target or None if not found
        """
        detections = self.detect(frame)

        # Normalize target name
        target_name = target_name.lower().strip()

        # Find best match
        best_match = None
        for detection in detections:
            if detection.class_name.lower() == target_name:
                if best_match is None or detection.confidence > best_match.confidence:
                    best_match = detection

        return best_match

    def get_common_classes(self) -> list[str]:
        """Get list of detectable object class names.

        Returns:
            List of class names
        """
        if self.model is None:
            return []
        return sorted({READABLE_NAMES.get(name, name) for name in self.model.names.values()})

    def visualize_detections(
        self,
        frame: np.ndarray,
        detections: list[Detection],
        thickness: int = 2,
    ) -> np.ndarray:
        """Draw detections on frame.

        Args:
            frame: RGB numpy array
            detections: List of Detection objects
            thickness: Line thickness

        Returns:
            Frame with bounding boxes drawn
        """
        frame_vis = frame.copy()

        for det in detections:
            x1, y1, x2, y2 = det.bbox
            x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)

            # Draw bounding box
            color = (0, 255, 0)  # Green
            cv2.rectangle(frame_vis, (x1, y1), (x2, y2), color, thickness)

            # Draw label
            label = f"{det.class_name} {det.confidence:.2f}"
            font = cv2.FONT_HERSHEY_SIMPLEX
            cv2.putText(
                frame_vis,
                label,
                (x1, y1 - 10),
                font,
                0.5,
                color,
                1,
            )

        return frame_vis


# Global detector instance
_detector: Optional[ObjectDetector] = None


def get_detector() -> ObjectDetector:
    """Get or create global object detector, configured from env (config.py):
    YOLO_MODEL (default yolo11m), YOLO_CONF (0.25), YOLO_IOU (0.45)."""
    global _detector
    if _detector is None:
        try:
            from src.common.config import YOLO_MODEL, YOLO_CONF, YOLO_IOU
        except Exception:
            YOLO_MODEL, YOLO_CONF, YOLO_IOU = "yolo11m", 0.25, 0.45
        _detector = ObjectDetector(
            model_name=YOLO_MODEL,
            confidence_threshold=YOLO_CONF,
            iou_threshold=YOLO_IOU,
        )
    return _detector


def init_detector(
    model_name: str = "yolo11m",
    confidence_threshold: float = 0.5,
    iou_threshold: float = 0.45
) -> ObjectDetector:
    """Initialize object detector.

    Args:
        model_name: YOLO model name (yolo11m, yolo11s, etc.)
        confidence_threshold: Minimum confidence (0.0-1.0), default 0.5
        iou_threshold: NMS IoU threshold (0.0-1.0), default 0.45

    Returns:
        ObjectDetector instance
    """
    global _detector
    _detector = ObjectDetector(
        model_name=model_name,
        confidence_threshold=confidence_threshold,
        iou_threshold=iou_threshold
    )
    return _detector
