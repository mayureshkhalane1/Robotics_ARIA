"""
Test suite for visual memory system.

Tests storage, loop closure detection, and spatial/temporal queries.
"""

import pytest
import numpy as np
from datetime import datetime, timedelta
import time
import logging
from PIL import Image, ImageDraw

from src.agent.visual_memory import VisualMemory, Observation, LoopClosureCandidate

logger = logging.getLogger(__name__)


class TestVisualMemoryBasics:
    """Test basic storage and retrieval."""
    
    @pytest.fixture
    def memory(self):
        """Create a VisualMemory instance."""
        return VisualMemory(max_observations=100, loop_closure_threshold=8)
    
    @pytest.fixture
    def sample_frame(self):
        """Create a sample BGR frame."""
        # Create a 480x640 BGR image
        frame = np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8)
        return frame
    
    @pytest.fixture
    def sample_pose(self):
        """Create a sample pose."""
        return (1.0, 2.0, 0.0, 0.0, 0.0, 0.5)  # x, y, z, roll, pitch, yaw
    
    def test_add_observation(self, memory, sample_frame, sample_pose):
        """Test adding an observation."""
        obs_id = memory.add_observation(
            frame=sample_frame,
            pose=sample_pose,
            timestamp=time.time(),
            camera_id="webots_camera_0",
        )
        
        assert obs_id.startswith("obs_")
        assert memory.get_observation(obs_id) is not None
    
    def test_observation_count(self, memory, sample_frame, sample_pose):
        """Test that observations are stored."""
        for i in range(10):
            memory.add_observation(
                frame=sample_frame,
                pose=sample_pose,
                timestamp=time.time() + i,
            )
        
        stats = memory.get_stats()
        assert stats["num_observations"] == 10
    
    def test_max_observations_limit(self, memory, sample_frame, sample_pose):
        """Test that memory doesn't exceed max_observations."""
        # Add more observations than max
        for i in range(150):
            memory.add_observation(
                frame=sample_frame,
                pose=sample_pose,
                timestamp=time.time() + i,
            )
        
        stats = memory.get_stats()
        assert stats["num_observations"] <= 100
        assert stats["memory_full"]
    
    def test_get_frame(self, memory, sample_frame, sample_pose):
        """Test retrieving frame data."""
        obs_id = memory.add_observation(
            frame=sample_frame,
            pose=sample_pose,
            timestamp=time.time(),
        )
        
        retrieved_frame = memory.get_frame(obs_id)
        assert retrieved_frame is not None
        assert retrieved_frame.shape == sample_frame.shape
        np.testing.assert_array_equal(retrieved_frame, sample_frame)
    
    def test_clear_memory(self, memory, sample_frame, sample_pose):
        """Test clearing all observations."""
        for i in range(10):
            memory.add_observation(
                frame=sample_frame,
                pose=sample_pose,
                timestamp=time.time() + i,
            )
        
        memory.clear_memory()
        stats = memory.get_stats()
        assert stats["num_observations"] == 0


class TestLoopClosureDetection:
    """Test loop closure detection."""
    
    @pytest.fixture
    def memory(self):
        return VisualMemory(max_observations=100, loop_closure_threshold=8)
    
    def create_test_frame(self, pattern_id: int) -> np.ndarray:
        """Create a test frame with a specific pattern."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        
        # Create distinct patterns for different pattern_ids
        if pattern_id == 0:
            # Red square in center
            frame[200:280, 270:370] = [0, 0, 255]  # BGR format, so red is [0, 0, 255]
        elif pattern_id == 1:
            # Blue square in center
            frame[200:280, 270:370] = [255, 0, 0]  # BGR format, blue is [255, 0, 0]
        elif pattern_id == 2:
            # Green square in center
            frame[200:280, 270:370] = [0, 255, 0]  # BGR format, green is [0, 255, 0]
        
        return frame
    
    def test_no_loop_closure_on_empty_memory(self, memory):
        """Test that empty memory returns None."""
        frame = np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8)
        result = memory.find_loop_closure(frame)
        assert result is None
    
    def test_loop_closure_same_frame(self, memory):
        """Test detecting when same frame is seen again."""
        # Create a distinctive frame
        frame = self.create_test_frame(0)
        pose = (1.0, 2.0, 0.0, 0.0, 0.0, 0.0)
        
        # Add it to memory
        memory.add_observation(
            frame=frame,
            pose=pose,
            timestamp=time.time(),
        )
        
        # Query with same frame
        result = memory.find_loop_closure(frame)
        
        assert result is not None
        assert result.similarity_score > 0.95  # Should be very similar
        assert result.hash_distance <= 8
    
    def test_no_loop_closure_different_patterns(self, memory):
        """Test that very different patterns are less likely to match."""
        # Use random noise to ensure differences
        np.random.seed(42)
        frame0 = np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8)
        
        np.random.seed(99)  # Different seed for completely different image
        frame1 = np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8)
        
        pose = (1.0, 2.0, 0.0, 0.0, 0.0, 0.0)
        
        # Add frame 0 to memory
        memory.add_observation(
            frame=frame0,
            pose=pose,
            timestamp=time.time(),
        )
        
        # Query with completely different frame
        result = memory.find_loop_closure(frame1)
        
        # With random images, they should have high Hamming distance
        if result is not None:
            # If a match is found, it should have low similarity
            assert result.hash_distance > 8 or result.similarity_score < 0.80
    
    def test_loop_closure_noisy_frame(self, memory):
        """Test loop closure with slight noise/compression artifacts."""
        # Create a base frame with actual content (not just zeros)
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        # Add multiple distinct regions for better hash stability
        frame[100:200, 100:200] = [50, 100, 150]
        frame[250:350, 250:350] = [200, 150, 100]
        frame[50:150, 400:500] = [100, 200, 50]
        
        pose = (1.0, 2.0, 0.0, 0.0, 0.0, 0.0)
        
        # Add to memory
        memory.add_observation(
            frame=frame.copy(),
            pose=pose,
            timestamp=time.time(),
        )
        
        # Create noisy version (small Gaussian noise - pHash is robust to this)
        noisy_frame = frame.copy().astype(float)
        noise = np.random.normal(0, 3, frame.shape)  # Small noise
        noisy_frame = np.clip(noisy_frame + noise, 0, 255).astype(np.uint8)
        
        # Should detect loop closure (pHash is robust to compression/noise)
        result = memory.find_loop_closure(noisy_frame)
        assert result is not None, "pHash should be robust to small noise"
        assert result.hash_distance <= 10  # Allow reasonable tolerance
    
    def test_loop_closure_returns_correct_pose(self, memory):
        """Test that loop closure returns the correct pose estimate."""
        frame = self.create_test_frame(0)
        original_pose = (3.5, 4.2, 0.1, 0.0, 0.0, 1.57)
        
        obs_id = memory.add_observation(
            frame=frame,
            pose=original_pose,
            timestamp=time.time(),
        )
        
        result = memory.find_loop_closure(frame)
        
        assert result is not None
        assert result.obs_id == obs_id
        # Check pose estimate (first 3 elements are x, y, z)
        assert abs(result.pose_estimate[0] - original_pose[0]) < 0.01
        assert abs(result.pose_estimate[1] - original_pose[1]) < 0.01
        assert abs(result.pose_estimate[2] - original_pose[2]) < 0.01


class TestSpatialQueries:
    """Test spatial and temporal queries."""
    
    @pytest.fixture
    def memory(self):
        return VisualMemory(max_observations=100, loop_closure_threshold=8)
    
    @pytest.fixture
    def sample_frame(self):
        return np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8)
    
    def test_get_observations_near(self, memory, sample_frame):
        """Test spatial radius query."""
        # Add observations at different locations
        poses = [
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (2.0, 0.0, 0.0),
            (5.0, 0.0, 0.0),
        ]
        
        for i, pose in enumerate(poses):
            full_pose = pose + (0.0, 0.0, 0.0)
            memory.add_observation(
                frame=sample_frame.copy(),
                pose=full_pose,
                timestamp=time.time() + i,
            )
        
        # Query within radius 1.5 of origin
        nearby = memory.get_observations_near((0.0, 0.0, 0.0), 1.5)
        
        assert len(nearby) == 2  # Should find (0, 0) and (1, 0)
        # Should be sorted by distance
        assert nearby[0].pose[0] == 0.0
        assert nearby[1].pose[0] == 1.0
    
    def test_get_frame_history(self, memory, sample_frame):
        """Test temporal range query."""
        base_time = time.time()
        
        for i in range(5):
            memory.add_observation(
                frame=sample_frame.copy(),
                pose=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
                timestamp=base_time + i,
            )
        
        # Query frames within specific time range
        start = base_time + 1
        end = base_time + 3
        history = memory.get_frame_history(start, end)
        
        assert len(history) == 3
        assert history[0].timestamp == base_time + 1
        assert history[-1].timestamp == base_time + 3
    
    def test_recall_object_location(self, memory, sample_frame):
        """Test object recall query."""
        # Add observations with different objects
        obs_id1 = memory.add_observation(
            frame=sample_frame.copy(),
            pose=(1.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            timestamp=time.time(),
            detected_objects={"cup": [[10, 20, 50, 60]]},
        )
        
        obs_id2 = memory.add_observation(
            frame=sample_frame.copy(),
            pose=(2.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            timestamp=time.time() + 1,
            detected_objects={"chair": [[15, 25, 55, 65]]},
        )
        
        obs_id3 = memory.add_observation(
            frame=sample_frame.copy(),
            pose=(3.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            timestamp=time.time() + 2,
            detected_objects={"cup": [[10, 20, 50, 60]], "table": [[0, 0, 100, 100]]},
        )
        
        # Recall where cup was seen
        cup_locations = memory.recall_object_location("cup")
        
        assert len(cup_locations) == 2
        assert cup_locations[0][0] == obs_id1
        assert cup_locations[1][0] == obs_id3


class TestThreadSafety:
    """Test thread safety of visual memory."""
    
    @pytest.fixture
    def memory(self):
        return VisualMemory(max_observations=100, loop_closure_threshold=8)
    
    def test_concurrent_writes(self, memory):
        """Test that concurrent writes don't cause race conditions."""
        import threading
        
        frame = np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8)
        pose = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        
        def add_observations(thread_id, count):
            for i in range(count):
                memory.add_observation(
                    frame=frame.copy(),
                    pose=pose,
                    timestamp=time.time() + thread_id * 100 + i,
                )
        
        threads = []
        for i in range(5):
            t = threading.Thread(target=add_observations, args=(i, 10))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        stats = memory.get_stats()
        assert stats["num_observations"] == 50


def create_test_frame_with_pattern(pattern_type: str = "solid") -> np.ndarray:
    """
    Create a test frame for integration testing.
    
    Args:
        pattern_type: Type of pattern ("solid", "checkerboard", "gradient")
    
    Returns:
        BGR numpy array frame (480x640x3)
    """
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    
    if pattern_type == "solid":
        frame[:, :] = [100, 150, 200]  # BGR
    elif pattern_type == "checkerboard":
        block_size = 20
        for i in range(0, 480, block_size):
            for j in range(0, 640, block_size):
                if (i // block_size + j // block_size) % 2:
                    frame[i:i+block_size, j:j+block_size] = [255, 100, 50]
    elif pattern_type == "gradient":
        for i in range(480):
            frame[i, :] = [i % 256, 128, 255 - (i % 256)]
    
    return frame


@pytest.mark.integration
class TestVisualMemoryIntegration:
    """Integration tests with sample images."""
    
    def test_with_generated_frames(self):
        """Test visual memory with synthetically generated frames."""
        memory = VisualMemory(max_observations=10)
        
        # Add frames with different patterns
        patterns = ["solid", "checkerboard", "gradient"]
        obs_ids = []
        
        for i, pattern in enumerate(patterns * 2):  # Repeat to create revisits
            frame = create_test_frame_with_pattern(pattern)
            obs_id = memory.add_observation(
                frame=frame,
                pose=(i, 0.0, 0.0, 0.0, 0.0, 0.0),
                timestamp=time.time() + i,
                camera_id="test_camera",
            )
            obs_ids.append(obs_id)
        
        # Check memory state
        stats = memory.get_stats()
        assert stats["num_observations"] == 6
        
        # Test loop closure on revisited pattern
        revisit_frame = create_test_frame_with_pattern("solid")
        result = memory.find_loop_closure(revisit_frame)
        
        assert result is not None, "Should detect revisit to 'solid' pattern"
        assert result.similarity_score > 0.90
    
    def test_frame_format_from_shark(self):
        """Test compatibility with Shark's frame format."""
        memory = VisualMemory()
        
        # Simulate frame from Shark
        test_frame_dict = {
            "frame": np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8),
            "timestamp": time.time(),
            "camera_id": "webots_camera_0",
            "resolution": (480, 640),
            "metadata": {
                "brightness": 0.75,
                "exposure_time": 0.016,
                "focal_length": 4.5,
            }
        }
        
        # Add observation
        obs_id = memory.add_observation(
            frame=test_frame_dict["frame"],
            pose=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            timestamp=test_frame_dict["timestamp"],
            camera_id=test_frame_dict["camera_id"],
        )
        
        # Retrieve and verify
        obs = memory.get_observation(obs_id)
        assert obs is not None
        assert obs.camera_id == "webots_camera_0"
        assert obs.frame.shape == (480, 640, 3)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
