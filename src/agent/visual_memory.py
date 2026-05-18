"""
Visual memory system for ARIA robot agent.

Stores camera frames with timestamps and pose information, detects loop closures
(when the robot returns to previously seen locations), and provides efficient
similarity matching through perceptual hashing.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Tuple, Dict, List
from datetime import datetime
import threading
import numpy as np
from PIL import Image
import imagehash
import time

logger = logging.getLogger(__name__)


@dataclass
class Observation:
    """A single observed frame with associated metadata."""
    
    obs_id: str
    frame: np.ndarray  # BGR image array (H, W, 3), uint8
    timestamp: float  # Seconds since epoch
    pose: Tuple[float, float, float, float, float, float]  # (x, y, z, roll, pitch, yaw)
    camera_id: str  # e.g., "webots_camera_0"
    perceptual_hash: imagehash.ImageHash = field(default=None)
    detected_objects: Dict[str, List] = field(default_factory=dict)  # object_name -> [bboxes]
    created_at: datetime = field(default_factory=datetime.now)
    
    def __post_init__(self):
        """Compute perceptual hash after initialization."""
        if self.perceptual_hash is None:
            self.perceptual_hash = self._compute_phash()
    
    def _compute_phash(self) -> imagehash.ImageHash:
        """Compute perceptual hash from frame."""
        try:
            # Convert BGR to RGB for PIL
            frame_rgb = self.frame[..., ::-1]
            pil_image = Image.fromarray(frame_rgb)
            return imagehash.phash(pil_image)
        except Exception as e:
            logger.warning(f"Failed to compute pHash for obs {self.obs_id}: {e}")
            return imagehash.ImageHash('0000000000000000')  # Default empty hash
    
    def hash_distance(self, other_hash: imagehash.ImageHash) -> int:
        """Compute Hamming distance to another hash."""
        return self.perceptual_hash - other_hash


@dataclass
class LoopClosureCandidate:
    """Result of a loop closure query."""
    obs_id: str
    similarity_score: float  # 1.0 = identical, 0.0 = different
    hash_distance: int  # Hamming distance (lower is more similar)
    pose_estimate: Tuple[float, float, float]  # (x, y, z)
    frame_age_seconds: float  # How old this observation is
    matched_frame: Optional[np.ndarray] = None  # For debugging


class VisualMemory:
    """
    Thread-safe visual memory system for storing and retrieving observations.
    
    Detects loop closures through perceptual hashing and supports spatial queries.
    """
    
    def __init__(self, max_observations: int = 100, loop_closure_threshold: int = 8):
        """
        Initialize visual memory.
        
        Args:
            max_observations: Maximum number of frames to keep in memory
            loop_closure_threshold: Hamming distance threshold for loop closure detection
                                   (0-64, lower = stricter matching). Default 8 = ~12% difference
        """
        self.max_observations = max_observations
        self.loop_closure_threshold = loop_closure_threshold
        self.observations: deque = deque(maxlen=max_observations)
        self.obs_by_id: Dict[str, Observation] = {}
        self.obs_id_counter = 0
        self._lock = threading.RLock()
        logger.info(f"VisualMemory initialized: max_obs={max_observations}, "
                   f"lc_threshold={loop_closure_threshold}")
    
    def add_observation(
        self,
        frame: np.ndarray,
        pose: Tuple[float, float, float, float, float, float],
        timestamp: float,
        camera_id: str = "webots_camera_0",
        detected_objects: Optional[Dict[str, List]] = None,
    ) -> str:
        """
        Add a new observation to memory.
        
        Args:
            frame: Camera frame as BGR numpy array (H, W, 3), uint8
            pose: Robot pose as (x, y, z, roll, pitch, yaw)
            timestamp: Timestamp in seconds since epoch
            camera_id: Identifier for the camera
            detected_objects: Dict mapping object names to lists of bounding boxes
        
        Returns:
            observation_id (string UUID-like identifier)
        """
        with self._lock:
            # Generate observation ID
            self.obs_id_counter += 1
            obs_id = f"obs_{self.obs_id_counter:06d}"
            
            # Create observation
            obs = Observation(
                obs_id=obs_id,
                frame=frame.copy(),  # Store copy to avoid external modification
                timestamp=timestamp,
                pose=pose,
                camera_id=camera_id,
                detected_objects=detected_objects or {},
            )
            
            # Add to memory
            self.observations.append(obs)
            self.obs_by_id[obs_id] = obs
            
            # Clean up old observations if deque is full
            # (deque auto-removes oldest, but we need to clean the dict)
            if len(self.obs_by_id) > self.max_observations:
                # Find and remove oldest observation
                oldest_id = min(self.obs_by_id.keys(),
                              key=lambda k: self.obs_by_id[k].timestamp)
                del self.obs_by_id[oldest_id]
            
            logger.debug(f"Added observation {obs_id} at pose {pose[:3]}")
            return obs_id
    
    def find_loop_closure(
        self,
        frame: np.ndarray,
        current_pose: Optional[Tuple[float, float, float]] = None,
    ) -> Optional[LoopClosureCandidate]:
        """
        Detect if the robot has returned to a previously seen location.
        
        Uses perceptual hashing for fast similarity matching. Returns the most
        similar observation from memory if similarity exceeds threshold.
        
        Args:
            frame: Current camera frame as BGR numpy array
            current_pose: Optional current pose for temporal filtering
        
        Returns:
            LoopClosureCandidate if match found, None otherwise
        """
        with self._lock:
            if not self.observations:
                return None
            
            # Compute hash for current frame
            try:
                frame_rgb = frame[..., ::-1]
                pil_image = Image.fromarray(frame_rgb)
                current_hash = imagehash.phash(pil_image)
            except Exception as e:
                logger.warning(f"Failed to compute hash for current frame: {e}")
                return None
            
            # Find best match
            best_match = None
            best_distance = float('inf')
            
            for obs in self.observations:
                distance = current_hash - obs.perceptual_hash
                
                if distance < best_distance:
                    best_distance = distance
                    best_match = obs
            
            # Check if best match exceeds threshold
            if best_match is None or best_distance > self.loop_closure_threshold:
                logger.debug(f"No loop closure found (best_distance={best_distance}, "
                           f"threshold={self.loop_closure_threshold})")
                return None
            
            # Compute similarity score (0-1)
            # Max Hamming distance for 64-bit hash is 64
            similarity = 1.0 - (best_distance / 64.0)
            
            # Compute frame age
            current_time = time.time()
            frame_age = current_time - best_match.timestamp
            
            candidate = LoopClosureCandidate(
                obs_id=best_match.obs_id,
                similarity_score=similarity,
                hash_distance=best_distance,
                pose_estimate=best_match.pose[:3],
                frame_age_seconds=frame_age,
                matched_frame=best_match.frame.copy(),
            )
            
            logger.info(f"Loop closure detected: {best_match.obs_id} "
                       f"(distance={best_distance}, similarity={similarity:.2%})")
            return candidate
    
    def get_observations_near(
        self,
        pose: Tuple[float, float, float],
        radius: float,
    ) -> List[Observation]:
        """
        Get all observations within a spatial radius of the given pose.
        
        Args:
            pose: Query pose (x, y, z)
            radius: Search radius in world units
        
        Returns:
            List of observations within radius, sorted by distance
        """
        with self._lock:
            nearby = []
            
            for obs in self.observations:
                obs_pos = obs.pose[:3]
                distance = np.linalg.norm(
                    np.array(pose) - np.array(obs_pos)
                )
                
                if distance <= radius:
                    nearby.append((obs, distance))
            
            # Sort by distance
            nearby.sort(key=lambda x: x[1])
            return [obs for obs, _ in nearby]
    
    def get_frame_history(
        self,
        start_time: float,
        end_time: float,
    ) -> List[Observation]:
        """
        Get all observations within a time range.
        
        Args:
            start_time: Start timestamp (seconds since epoch)
            end_time: End timestamp (seconds since epoch)
        
        Returns:
            List of observations in chronological order
        """
        with self._lock:
            result = [
                obs for obs in self.observations
                if start_time <= obs.timestamp <= end_time
            ]
            return sorted(result, key=lambda x: x.timestamp)
    
    def recall_object_location(
        self,
        object_name: str,
    ) -> List[Tuple[str, Observation]]:
        """
        Find all observations where a specific object was detected.
        
        Args:
            object_name: Name of the object to search for
        
        Returns:
            List of (obs_id, Observation) tuples where object was seen
        """
        with self._lock:
            results = [
                (obs.obs_id, obs)
                for obs in self.observations
                if object_name in obs.detected_objects
            ]
            return results
    
    def get_observation(self, obs_id: str) -> Optional[Observation]:
        """
        Retrieve a specific observation by ID.
        
        Args:
            obs_id: Observation identifier
        
        Returns:
            Observation if found, None otherwise
        """
        with self._lock:
            return self.obs_by_id.get(obs_id)
    
    def get_frame(self, obs_id: str) -> Optional[np.ndarray]:
        """
        Retrieve just the frame data from an observation.
        
        Args:
            obs_id: Observation identifier
        
        Returns:
            Frame as BGR numpy array, or None if not found
        """
        with self._lock:
            obs = self.obs_by_id.get(obs_id)
            return obs.frame.copy() if obs else None
    
    def clear_memory(self) -> None:
        """Clear all observations from memory."""
        with self._lock:
            self.observations.clear()
            self.obs_by_id.clear()
            logger.info("Visual memory cleared")
    
    def get_stats(self) -> Dict:
        """
        Get memory statistics.
        
        Returns:
            Dictionary with stats: num_observations, oldest_timestamp, newest_timestamp, etc.
        """
        with self._lock:
            if not self.observations:
                return {
                    "num_observations": 0,
                    "memory_full": False,
                }
            
            timestamps = [obs.timestamp for obs in self.observations]
            frame_ages = [
                time.time() - ts
                for ts in timestamps
            ]
            
            return {
                "num_observations": len(self.observations),
                "memory_full": len(self.observations) >= self.max_observations,
                "oldest_age_seconds": max(frame_ages),
                "newest_age_seconds": min(frame_ages),
                "average_age_seconds": np.mean(frame_ages),
            }


# Global visual memory instance
_visual_memory: Optional['VisualMemory'] = None


def get_visual_memory() -> VisualMemory:
    """Get or create global visual memory.

    Returns:
        VisualMemory instance
    """
    global _visual_memory
    if _visual_memory is None:
        _visual_memory = VisualMemory(max_observations=100)
    return _visual_memory


def init_visual_memory(max_observations: int = 100) -> VisualMemory:
    """Initialize visual memory.

    Args:
        max_observations: Maximum observations to keep

    Returns:
        VisualMemory instance
    """
    global _visual_memory
    _visual_memory = VisualMemory(max_observations=max_observations)
    return _visual_memory
