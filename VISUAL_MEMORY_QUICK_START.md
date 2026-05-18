# Visual Memory - Quick Start Guide

## Installation

```bash
cd ./Documents/ARIA
pip install imagehash  # Or: uv add imagehash
```

## Basic Usage

```python
from src.agent.visual_memory import VisualMemory
import time

# Initialize
visual_memory = VisualMemory(max_observations=100, loop_closure_threshold=8)

# Store an observation
obs_id = visual_memory.add_observation(
    frame=frame_bgr,                    # np.ndarray (H, W, 3)
    pose=(x, y, z, roll, pitch, yaw),   # 6-tuple of floats
    timestamp=time.time(),
    camera_id="webots_camera_0",
    detected_objects={"cup": [[10,20,50,60]]}
)

# Detect loop closure (revisiting place)
result = visual_memory.find_loop_closure(frame_bgr)
if result:
    print(f"Found {result.obs_id} with {result.similarity_score:.0%} similarity")
    print(f"Was there {result.frame_age_seconds:.1f}s ago at {result.pose_estimate}")
```

## Common Queries

```python
# Find observations within 2 meters
nearby = visual_memory.get_observations_near((1.0, 2.0, 0.0), radius=2.0)

# Get last 10 seconds of frames
import time
now = time.time()
recent = visual_memory.get_frame_history(now - 10, now)

# Find where object was seen
cup_locations = visual_memory.recall_object_location("cup")
if cup_locations:
    last_obs_id, last_obs = cup_locations[-1]
    print(f"Cup at {last_obs.pose[:3]}")

# Get memory stats
stats = visual_memory.get_stats()
print(f"Memory: {stats['num_observations']} frames, "
      f"avg age {stats['average_age_seconds']:.1f}s")
```

## Integration with Agent Main Loop

```python
def sense():
    frame = camera.get_frame()
    pose = robot.get_pose()
    
    # Store and check for loop closure
    obs_id = visual_memory.add_observation(frame, pose, time.time())
    lc = visual_memory.find_loop_closure(frame)
    
    return {"frame": frame, "obs_id": obs_id, "loop_closure": lc}

def plan(goal, sense_data):
    if sense_data["loop_closure"]:
        # Robot returned to known location
        return "Revisiting known area - use alternate strategy"
    
    # Check if we've seen target object before
    if "find cup" in goal:
        locations = visual_memory.recall_object_location("cup")
        if locations:
            return "Found cup in memory - moving to known location"
    
    # Default: explore new areas
    return "Exploring..."
```

## Configuration

```python
# Stricter matching (only very similar images)
memory = VisualMemory(max_observations=100, loop_closure_threshold=5)

# Looser matching (more false positives, finds similar environments)
memory = VisualMemory(max_observations=100, loop_closure_threshold=12)

# Smaller memory (resource constrained)
memory = VisualMemory(max_observations=50)

# Larger memory (more storage available)
memory = VisualMemory(max_observations=200)
```

## Debugging

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Now you'll see:
# "Added observation obs_000001 at pose (1.0, 2.0, 0.0)"
# "Loop closure detected: obs_000001 (distance=5, similarity=92%)"
```

## Testing

```bash
# Run all tests
python3 -m pytest tests/test_visual_memory.py -v

# Run specific test
python3 -m pytest tests/test_visual_memory.py::TestLoopClosureDetection -v

# With coverage
python3 -m pytest tests/test_visual_memory.py --cov=src.agent.visual_memory
```

## Performance Tips

1. **Loop Closure Threshold**: Adjust for your environment
   - Indoor/structured: threshold=8 (default, good)
   - Outdoor/varied: threshold=10-12 (handle variation)
   - High accuracy needed: threshold=5-6

2. **Memory Size**: Balance between coverage and speed
   - threshold=8 with 100 obs: ~10ms loop closure search
   - threshold=8 with 50 obs: ~5ms loop closure search

3. **Future**: JPEG compression reduces storage 10-20x

## API Reference

| Method | Purpose | Time |
|--------|---------|------|
| `add_observation()` | Store frame + metadata | O(1), <1ms |
| `find_loop_closure()` | Detect revisited place | O(n), 5-10ms |
| `get_observations_near()` | Spatial query | O(n log n), 2-5ms |
| `get_frame_history()` | Temporal query | O(n log n), 1-3ms |
| `recall_object_location()` | Find object | O(n), 1-2ms |
| `get_observation()` | Get by ID | O(1), <1ms |
| `get_frame()` | Get image data | O(1), <1ms |
| `clear_memory()` | Reset all | O(1), <1ms |

## Full Documentation

See `docs/VISUAL_MEMORY_API.md` for complete API reference and architecture details.
