# Visual Memory System - ARIA Robotics Agent

## Overview

The Visual Memory module (`src/agent/visual_memory.py`) is a thread-safe system for storing robot camera observations and detecting when the robot returns to previously visited locations (loop closure detection).

### Key Features

- **Observation Storage**: Stores camera frames with pose and timestamp metadata
- **Loop Closure Detection**: Detects when robot revisits locations using perceptual hashing
- **Spatial Queries**: Find observations near a given location
- **Temporal Queries**: Retrieve observations from specific time ranges
- **Object Memory**: Track where specific objects were last observed
- **Thread-Safe**: Safe for concurrent access from multiple threads

## Architecture

```
                    ┌─────────────────────┐
                    │   Robot Sensors     │
                    │ (Camera + Pose)     │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │ Visual Memory Add   │
                    │ (Store Observation) │
                    └──────────┬──────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        │                      │                      │
        ▼                      ▼                      ▼
    Deque Storage      Hash Index         Pose Index
    (Last 100 obs)  (pHash -> obs_id)  (Spatial tree)
```

## API Reference

### Core Classes

#### `Observation`
Represents a single camera frame with metadata.

```python
@dataclass
class Observation:
    obs_id: str                                      # Unique identifier
    frame: np.ndarray                               # BGR image (H, W, 3)
    timestamp: float                                # Unix timestamp
    pose: Tuple[float, float, float, ...]          # (x, y, z, roll, pitch, yaw)
    camera_id: str                                  # Camera source ID
    perceptual_hash: imagehash.ImageHash           # pHash for matching
    detected_objects: Dict[str, List]              # Objects seen {name: [bboxes]}
```

#### `LoopClosureCandidate`
Result of loop closure detection query.

```python
@dataclass
class LoopClosureCandidate:
    obs_id: str                    # Matched observation ID
    similarity_score: float        # 0.0-1.0, 1.0 = identical
    hash_distance: int             # Hamming distance (0-64)
    pose_estimate: Tuple          # (x, y, z) of matched location
    frame_age_seconds: float       # How old the matched frame is
    matched_frame: np.ndarray      # Copy of matched frame
```

#### `VisualMemory`
Main class for managing observations and queries.

```python
class VisualMemory:
    def __init__(
        self,
        max_observations: int = 100,
        loop_closure_threshold: int = 8,
    ):
        """
        Initialize visual memory.
        
        Args:
            max_observations: Max frames to keep (older ones auto-evicted)
            loop_closure_threshold: Hamming distance threshold
                - 0-3: Very strict (only nearly identical frames)
                - 4-8: Strict (same location, slight variations)
                - 9-16: Moderate (recognizable locations)
                - 17+: Loose (similar environments)
        """
```

### Main Methods

#### `add_observation()`
Store a new camera frame and metadata.

```python
def add_observation(
    self,
    frame: np.ndarray,                    # BGR array (H, W, 3), uint8
    pose: Tuple[float, ...],              # (x, y, z, roll, pitch, yaw)
    timestamp: float,                      # Unix time in seconds
    camera_id: str = "webots_camera_0",
    detected_objects: Optional[Dict] = None,
) -> str:
    """
    Returns: observation_id like "obs_000042"
    
    Example:
        obs_id = memory.add_observation(
            frame=frame,                      # np.ndarray (480, 640, 3)
            pose=(1.5, 2.3, 0.0, 0, 0, 1.57),
            timestamp=time.time(),
            detected_objects={"cup": [[10,20,50,60]], "chair": [...]}
        )
    """
```

#### `find_loop_closure()`
Detect if current frame matches a previously stored observation.

```python
def find_loop_closure(
    self,
    frame: np.ndarray,                           # BGR array to match
    current_pose: Optional[Tuple[float, ...]] = None,
) -> Optional[LoopClosureCandidate]:
    """
    Uses perceptual hashing (pHash) for fast similarity matching.
    
    Returns: LoopClosureCandidate if match found, None otherwise
    
    Example:
        result = memory.find_loop_closure(frame)
        if result:
            print(f"Matched {result.obs_id} with {result.similarity_score:.1%} similarity")
            print(f"That was {result.frame_age_seconds:.1f}s ago")
            print(f"Robot was at {result.pose_estimate}")
    """
```

#### `get_observations_near()`
Find all observations within a spatial radius.

```python
def get_observations_near(
    self,
    pose: Tuple[float, float, float],    # (x, y, z) query position
    radius: float,                        # Search radius in meters
) -> List[Observation]:
    """
    Returns: List of observations sorted by distance (nearest first)
    
    Example:
        nearby = memory.get_observations_near((0.0, 0.0, 0.0), radius=2.0)
        if nearby:
            nearest = nearby[0]
            print(f"Nearest observation: {nearest.obs_id} at {nearest.pose[:3]}")
    """
```

#### `get_frame_history()`
Retrieve observations from a specific time range.

```python
def get_frame_history(
    self,
    start_time: float,    # Unix timestamp
    end_time: float,      # Unix timestamp
) -> List[Observation]:
    """
    Returns: List of observations in chronological order
    
    Example:
        now = time.time()
        recent = memory.get_frame_history(now - 10, now)  # Last 10 seconds
    """
```

#### `recall_object_location()`
Find where a specific object was last observed.

```python
def recall_object_location(
    self,
    object_name: str,    # e.g., "cup", "chair"
) -> List[Tuple[str, Observation]]:
    """
    Returns: List of (obs_id, observation) where object was detected
    
    Example:
        locations = memory.recall_object_location("cup")
        if locations:
            last_seen = locations[-1]  # Most recent
            print(f"Cup was at {last_seen[1].pose[:3]}")
    """
```

#### `get_observation()`
Retrieve a specific observation by ID.

```python
def get_observation(self, obs_id: str) -> Optional[Observation]:
    """Returns: Observation object or None if not found"""
```

#### `get_frame()`
Retrieve just the image data from an observation.

```python
def get_frame(self, obs_id: str) -> Optional[np.ndarray]:
    """Returns: BGR numpy array or None"""
```

#### `get_stats()`
Get memory usage statistics.

```python
def get_stats(self) -> Dict:
    """
    Returns dictionary with:
        - num_observations: Current number of stored observations
        - memory_full: Boolean, True if at max capacity
        - oldest_age_seconds: Time since oldest observation
        - newest_age_seconds: Time since newest observation
        - average_age_seconds: Average age of all observations
    """
```

#### `clear_memory()`
Clear all observations.

```python
def clear_memory(self) -> None:
    """Removes all stored observations"""
```

## Integration with Agent Main Loop

### Minimal Integration

```python
from src.agent.visual_memory import VisualMemory
import time

# Initialize once
visual_memory = VisualMemory(max_observations=100, loop_closure_threshold=8)

# In agent sense() phase:
def sense():
    frame = get_camera_frame()  # BGR array
    pose = get_robot_pose()     # (x, y, z, roll, pitch, yaw)
    
    # Store observation
    obs_id = visual_memory.add_observation(
        frame=frame,
        pose=pose,
        timestamp=time.time(),
    )
    
    # Check for loop closure
    loop_closure = visual_memory.find_loop_closure(frame)
    
    return {
        "frame": frame,
        "obs_id": obs_id,
        "loop_closure": loop_closure,
    }

# In agent plan() phase:
def plan(goal, sense_data):
    if sense_data["loop_closure"]:
        lc = sense_data["loop_closure"]
        # Plan to revisit remembered location or different search strategy
        return f"Revisiting {lc.obs_id}"
    
    # Normal planning
    return "Exploring new area"
```

### Advanced Integration with Object Detection

```python
# In sense phase, after object detection:
obs_id = visual_memory.add_observation(
    frame=frame,
    pose=pose,
    timestamp=time.time(),
    detected_objects={
        "cup": [[10, 20, 50, 60], [100, 150, 140, 180]],
        "chair": [[200, 250, 350, 400]],
    }
)

# In plan phase, when goal is "find cup":
cup_locations = visual_memory.recall_object_location("cup")
if cup_locations:
    # Navigate to most recently observed location
    last_obs = cup_locations[-1][1]
    plan_navigation_to(last_obs.pose[:3])
```

## Data Format Compatibility

### Input Frame Format (from Shark/Camera)

Frames should be provided as:
```python
{
    "frame": np.ndarray,           # Shape (H, W, 3), dtype uint8
    "timestamp": float,            # Seconds since epoch
    "camera_id": str,
    "resolution": tuple,           # (height, width)
    "metadata": {
        "brightness": float,
        "exposure_time": float,
        "focal_length": float,
    }
}
```

The `add_observation()` method accepts the `frame`, `timestamp`, and `camera_id` fields directly.

### Output Format (for Graph Mapper/Cockroach)

Observations contain detected_objects in format:
```python
detected_objects = {
    "object_class": [
        [x1, y1, x2, y2],        # Bounding boxes in pixel coordinates
        [x1, y1, x2, y2],
    ],
}
```

## Performance Characteristics

| Operation | Time Complexity | Notes |
|-----------|-----------------|-------|
| `add_observation()` | O(1) | Amortized (deque operations + dict cleanup) |
| `find_loop_closure()` | O(n) | Linear scan of all observations |
| `get_observations_near()` | O(n) | Linear scan + sort |
| `get_frame_history()` | O(n) | Linear scan + sort |
| `recall_object_location()` | O(n) | Linear scan |
| Memory usage | O(n) | ~2MB per 480x640 frame (uncompressed) |

### Optimization Tips

1. **Use appropriate threshold**: Higher threshold (12-16) → faster matching but more false positives
2. **Limit observations**: 100 frames = ~200MB, adjust based on RAM
3. **Compression**: Consider JPEG-encoding frames before storage for production
4. **Indexing**: For many spatial queries, consider upgrading to spatial index (KD-tree)

## Testing

Run the test suite:
```bash
cd ./Documents/ARIA
python3 -m pytest tests/test_visual_memory.py -v
```

Test categories:
- **TestVisualMemoryBasics**: Storage and retrieval
- **TestLoopClosureDetection**: Loop closure matching
- **TestSpatialQueries**: Spatial and temporal queries
- **TestThreadSafety**: Concurrent access
- **TestVisualMemoryIntegration**: End-to-end integration

## Debugging

Enable logging to see detailed memory operations:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('src.agent.visual_memory')
```

Output debug information:
```python
stats = visual_memory.get_stats()
print(f"Memory: {stats['num_observations']} observations")
print(f"Oldest: {stats['oldest_age_seconds']:.1f}s")
```

## Dependencies

- `numpy`: Array operations
- `pillow`: Image processing
- `imagehash`: Perceptual hashing
- `threading`: Thread safety

Install via:
```bash
pip install imagehash pillow numpy
```

## Future Enhancements

1. **Deep Features**: Integrate CLIP embeddings for semantic similarity
2. **Spatial Indexing**: KD-tree for faster spatial queries
3. **Persistent Storage**: SQLite backend for session continuity
4. **Loop Closure Filtering**: Temporal constraints to avoid false positives
5. **Place Recognition**: CNN-based descriptor matching for robust matching
6. **Memory Compression**: JPEG or perceptual codecs to reduce storage

## References

- **Perceptual Hashing**: [imagehash documentation](https://github.com/JohannesBuchner/imagehash)
- **Loop Closure Detection**: Common in SLAM (Simultaneous Localization and Mapping)
- **Visual Memory in Robotics**: Used in navigation and exploration tasks
