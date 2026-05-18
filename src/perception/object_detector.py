"""YOLO-based object detector for robot perception."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np
from ultralytics import YOLO


# COCO class names that YOLO-Nano detects
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

    def __init__(self, model_name: str = "yolov8n", confidence_threshold: float = 0.5):
        """Initialize object detector.

        Args:
            model_name: YOLO model name (yolov8n, yolov8s, etc.)
            confidence_threshold: Minimum confidence to keep detections
        """
        self.model_name = model_name
        self.confidence_threshold = confidence_threshold

        # Load model (auto-downloads on first use)
        try:
            self.model = YOLO(f"{model_name}.pt")
            print(f"[Detector] Loaded {model_name} successfully")
        except Exception as e:
            print(f"[Detector] Failed to load model: {e}")
            self.model = None

    def detect(self, frame: np.ndarray) -> list[Detection]:
        """Detect objects in frame.

        Args:
            frame: RGB numpy array (HxWx3, uint8)

        Returns:
            List of Detection objects sorted by confidence
        """
        if self.model is None:
            print("[Detector] Model not loaded")
            return []

        if frame is None or frame.size == 0:
            print("[Detector] Invalid frame")
            return []

        try:
            # Run inference
            results = self.model(frame, verbose=False, conf=self.confidence_threshold)

            detections = []

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
        """Get list of commonly detectable objects.

        Returns:
            List of class names
        """
        return [
            "bottle",
            "cup",
            "chair",
            "table",
            "bed",
            "laptop",
            "monitor",
            "plant",
            "couch",
            "fork",
            "knife",
            "spoon",
        ]

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
    """Get or create global object detector.

    Returns:
        ObjectDetector instance
    """
    global _detector
    if _detector is None:
        _detector = ObjectDetector(model_name="yolov8n", confidence_threshold=0.5)
    return _detector


def init_detector(
    model_name: str = "yolov8n", confidence_threshold: float = 0.5
) -> ObjectDetector:
    """Initialize object detector.

    Args:
        model_name: YOLO model name
        confidence_threshold: Minimum confidence

    Returns:
        ObjectDetector instance
    """
    global _detector
    _detector = ObjectDetector(model_name=model_name, confidence_threshold=confidence_threshold)
    return _detector
