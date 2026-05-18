# ARIA Vision System - Architecture Blueprint

## Overall Pipeline

```
Webots Camera (320x240)
    ↓ (via MCP server)
Camera Stream Manager (src/perception/camera.py)
    ├→ Real-time feed to UI (WebSocket)
    ├→ Object Detection (YOLO-Nano)
    ├→ Visual Memory (frame storage + loop closure)
    └→ Environment Graph (nodes + observations)
         ↓
    Agent Planning Layer
         ↓
    Navigation toward detected target object
```

## Core Components to Build

### 1. Camera Streaming (src/perception/camera.py)
- **Purpose:** Get frames from Webots, stream to UI, distribute to perception modules
- **Key Methods:**
  - `get_frame()` → numpy array (uint8)
  - `get_frame_with_metadata()` → frame + pose + timestamp
  - WebSocket streaming at ~15 FPS
- **Dependencies:** MCP server (already works)
- **UI Integration:** Send JPEG-encoded frames via WebSocket

### 2. Object Detector (src/perception/object_detector.py)
- **Purpose:** Find target objects in camera feed
- **Model:** YOLO-Nano (lightweight, no GPU needed)
- **Key Methods:**
  - `detect(frame)` → list of (class_name, confidence, bbox)
  - `find_target(frame, target_name)` → Detection or None
- **Dependencies:** ultralytics (pip install ultralytics)
- **Output Format:** Bounding boxes in pixel coordinates

### 3. Visual Memory (src/agent/visual_memory.py)
- **Purpose:** Remember past frames, detect loop closures (revisiting places)
- **Key Methods:**
  - `add_observation(frame, pose, timestamp)` → observation_id
  - `find_loop_closure(frame)` → (similar_obs_id, similarity_score) or None
  - `get_frame(observation_id)` → frame
- **Storage:** Last 100 observations (configurable)
- **Loop Closure:** Image hashing (phash) + perceptual matching
- **Dependencies:** imagehash, PIL

### 4. Environment Graph (src/agent/environment_graph.py)
- **Purpose:** Spatial understanding of the world
- **Schema:**
  ```
  Node: {
    id, position (x,y,z), timestamp,
    observations: [obs_ids],
    objects_seen: {object_name: [bbox]},
    connectivity: frontier areas
  }
  Edge: {
    from_node, to_node, distance, traversability
  }
  ```
- **Key Methods:**
  - `add_observation(frame, pose, objects_detected, obs_id)`
  - `get_nearest_nodes(pose, radius)` → [nodes]
  - `path_to_unseen_area()` → waypoints
  - `get_object_locations(object_name)` → [(node_id, bbox)]
- **Dependencies:** networkx
- **Visualization:** Can export to GraphML or visualize with graphviz

### 5. Agent Integration (src/agent/graph.py)
**Modified Planning Logic:**
```python
def sense():
    frame = camera.get_frame_with_metadata()
    objects = object_detector.detect(frame)
    graph.add_observation(frame, pose, objects)
    return state_with_objects

def plan(goal, state):
    if goal = "find <object>":
        # Check if we've seen it before
        if object_locations := graph.get_object_locations(goal):
            return plan_to_nearest_object_location(object_locations)
        # Check if revisiting known area
        elif loop_closure := visual_memory.find_loop_closure(frame):
            return plan_to_revisit(loop_closure)
        # Explore unseen area
        else:
            return plan_exploration()
    # ... normal obstacle avoidance logic
```

## Implementation Order (Parallel)

1. **Phase 1 (Parallel):**
   - Camera streaming module (feeds all others)
   - Object detector basic setup
   - Visual memory storage
   - Graph schema

2. **Phase 2 (Dependent on Phase 1):**
   - UI camera display
   - Loop closure detection
   - Graph population during agent runs

3. **Phase 3 (Integration):**
   - Agent planning with graph awareness
   - Target-seeking behavior
   - Memory-based navigation

## Data Flow Example: "Find Cup"

```
User: "find cup"
  ↓
Agent loop iteration 1:
  sense() → frame from Webots
    ↓
  object_detector.detect(frame) → [("cup", 0.92, [x1,y1,x2,y2]), ...]
    ↓
  graph.add_observation(frame, pose, objects)
    ↓
  visual_memory.add_observation(frame, pose)
    ↓
  plan() → "cup found! Move toward [x1,y1,x2,y2] in frame"
    ↓
  act() → move forward/turn to center cup in frame

Agent loop iteration 2-N:
  If cup still visible: track it (keep centered)
  If cup lost: use memory + graph to search nearby nodes
  If area fully explored: return "goal failed"
```

## File Structure

```
src/
├── agent/
│   ├── main.py (existing)
│   ├── graph.py (MODIFY - add planning logic)
│   ├── nodes.py (existing)
│   ├── visual_memory.py (NEW)
│   └── environment_graph.py (NEW)
├── perception/
│   ├── __init__.py (NEW)
│   ├── camera.py (NEW)
│   └── object_detector.py (NEW)
├── mcp_server/
│   └── server.py (existing - no changes needed)
└── ui/
    ├── server.py (MODIFY - add camera stream endpoint)
    └── static/
        └── index.html (MODIFY - add camera display + object labels)
```

## Success Criteria

- [ ] Camera feeds to UI at 15+ FPS
- [ ] Object detector finds cups, chairs, tables with >80% accuracy
- [ ] Visual memory detects loop closures (same place revisited)
- [ ] Environment graph has 10+ nodes after 5-min exploration
- [ ] Agent finds target object within 50 steps
- [ ] UI shows real-time camera + detected objects + graph visualization
- [ ] Agent remembers locations: "I saw a cup in room 2, moving toward it"

## Dependencies to Install

```bash
pip install ultralytics pillow imagehash networkx opencv-python
```

Or via uv:
```bash
uv add ultralytics pillow imagehash networkx opencv-python
```
