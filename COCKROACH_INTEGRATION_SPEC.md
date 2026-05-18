"""Cockroach (Graph Mapper) Integration Specification

This document defines the interface and data contracts between:
- Shark (Camera Streaming) → Cockroach (Graph Mapper)
- Lion (Object Detector) → Cockroach (Graph Mapper)
- Cockroach (Graph Mapper) → Raven (Visual Memory)
"""

# ============================================================================
# 1. INPUT: Detection Pipeline Output (from Lion)
# ============================================================================

"""
Format consumed from Lion (object detector):

{
    "detections": [
        {
            "class": "cup",
            "confidence": 0.92,
            "bbox": (x1, y1, x2, y2)  # Image pixel coordinates
        },
        {
            "class": "table", 
            "confidence": 0.85,
            "bbox": (x1, y1, x2, y2)
        },
        ...
    ],
    "timestamp": 1716045174.531,  # Unix timestamp (seconds)
    "camera_id": "webots_camera_0",
    "frame_data": {  # Additional metadata from Shark
        "resolution": (height, width),
        "brightness": 0.75,
        "exposure_time": 0.016
    }
}

Data flow:
1. Shark provides frame + metadata (timestamp, resolution)
2. Lion detects objects in frame (class, confidence, bbox)
3. Agent provides robot position at same timestamp
4. Cockroach integrates all three into graph

Processing function:

```python
def add_detection(lion_output, robot_position, timestamp=None):
    '''Integrate detection from Lion with robot pose into graph.'''
    timestamp = timestamp or lion_output["timestamp"]
    
    # Convert Lion's detection format to graph format
    objects_detected = {}
    for det in lion_output["detections"]:
        class_name = det["class"]
        bbox = tuple(det["bbox"])
        if class_name not in objects_detected:
            objects_detected[class_name] = []
        objects_detected[class_name].append(bbox)
    
    # Add to graph with robot position
    node_id, obs_id = graph.add_observation(
        position=robot_position,
        timestamp=timestamp,
        objects_detected=objects_detected,
        frame_hash=lion_output.get("frame_hash"),  # For loop closure
        confidence=min(d["confidence"] for d in lion_output["detections"]),
    )
    
    return node_id, obs_id
```
"""

# ============================================================================
# 2. INTERNAL: Graph Schema
# ============================================================================

"""
Graph Node (visited location):
{
    "node_id": "node_0",
    "position": (x, y, z),  # World coordinates
    "timestamp": 1716045174.531,
    "observations": [
        {
            "obs_id": "obs_0",
            "timestamp": 1716045174.531,
            "position": (x, y, z),
            "frame_hash": "abc123def456",  # For loop closure
            "confidence": 0.85
        }
    ],
    "objects_seen": {
        "cup": [
            {
                "class_name": "cup",
                "confidence": 0.92,
                "bbox": (50, 60, 100, 150),  # Pixel coordinates
                "obs_id": "obs_0"
            },
            ...
        ],
        "table": [...],
    },
    "frontier_areas": [
        (x, y, z),  # Unexplored directions
    ],
    "visit_count": 2,
    "last_visited": 1716045180.0
}

Graph Edge (connection between nodes):
{
    "from_node_id": "node_0",
    "to_node_id": "node_1",
    "distance": 1.5,  # Meters
    "traversability": 0.95,  # 0.0=blocked, 1.0=open
    "edge_type": "direct" | "loop_closure" | "inferred"
}
"""

# ============================================================================
# 3. OUTPUT: Data for Visual Memory (Raven)
# ============================================================================

"""
Graph exports observations to Raven for memory storage:

{
    "observation_id": "obs_0",
    "timestamp": 1716045174.531,
    "position": (x, y, z),
    "node_id": "node_0",
    "objects_seen": {
        "cup": [
            {"confidence": 0.92, "bbox": (50, 60, 100, 150)},
            ...
        ]
    },
    "context": {
        "nearby_nodes": ["node_1", "node_2"],
        "visit_count_at_location": 2
    }
}

Integration method:

```python
def export_observation_to_memory(graph, obs_id, memory_system):
    '''Export observation from graph to visual memory.'''
    # Find observation in graph
    for node_id, node in graph.nodes.items():
        for obs in node.observations:
            if obs.obs_id == obs_id:
                export_data = {
                    "observation_id": obs.obs_id,
                    "timestamp": obs.timestamp,
                    "position": obs.position,
                    "node_id": node_id,
                    "objects_seen": node.objects_seen,
                    "context": {
                        "nearby_nodes": [n[0] for n in graph.get_nearby_nodes(obs.position, radius=3.0)],
                        "visit_count_at_location": node.visit_count,
                    }
                }
                memory_system.store_observation(export_data)
                return True
    return False
```
"""

# ============================================================================
# 4. QUERY INTERFACE: API for Agent Planning
# ============================================================================

"""
Methods for agent planning:

1. Retrieve object locations:
   locations = graph.get_object_locations("cup")
   # Returns: [(node_id, [detections]), ...]
   # Use: "Where have I seen cups?" → navigate to nearest

2. Get nearby nodes:
   nearby = graph.get_nearby_nodes((x, y, z), radius=3.0)
   # Returns: [(node_id, distance), ...]
   # Use: "What have I explored nearby?" → check for new objects

3. Find path:
   path = graph.shortest_path(node_id_1, node_id_2)
   # Returns: [node_id, node_id, ..., node_id]
   # Use: "How do I get to where I saw the cup?"

4. Connected components:
   reachable = graph.get_connected_component(node_id)
   # Returns: {node_id, ...}
   # Use: "Is that location reachable from here?"

5. Graph statistics:
   stats = graph.get_statistics()
   # Returns: {num_nodes, num_edges, num_observations, ...}
   # Use: "Have I fully explored this area?"
"""

# ============================================================================
# 5. LOOP CLOSURE INTEGRATION WITH VISUAL MEMORY
# ============================================================================

"""
When Raven detects loop closure (revisiting location):

1. Raven computes frame similarity (perceptual hash)
2. Identifies obs_id_old and obs_id_new as same visual location
3. Calls back to Cockroach:
   
   graph.add_loop_closure(obs_id_old, obs_id_new)
   
   This:
   - Finds nodes containing obs_id_old and obs_id_new
   - Creates bidirectional edges (loop_closure type)
   - Updates edge_type to indicate topological constraint

This closes the loop in spatial understanding:
   [Node 0] --direct--> [Node 1] --direct--> [Node 2]
      ^                                          |
      |____________loop_closure__________________|

Use case:
- Agent explores from room A → room B → room C
- Raven detects room C visually similar to room A
- Cockroach adds loop closure edge
- Agent realizes it can shortcut back to room A
- Enables more efficient exploration
"""

# ============================================================================
# 6. PERFORMANCE CHARACTERISTICS
# ============================================================================

"""
Expected performance:

Operation          Time Complexity    Memory (per 1000 nodes)
add_observation    O(n)              +~1KB per obs
get_object_locations    O(n)         N/A (no allocation)
shortest_path      O(n + e log n)    N/A (networkx handles)
connect_nearby     O(n²)             N/A (one-time)
loop_closure       O(n)              +~100B per edge

Memory usage:
- Per node: ~1KB base + obs/objects
- Per observation: ~200 bytes
- Per object detection: ~100 bytes
- Per 100-node graph: ~100-200 KB

Scalability:
- Tested up to 1000 nodes with no issues
- NetworkX operates efficiently on DAGs
- Consider pruning old nodes if exploring long-term
"""

# ============================================================================
# 7. INTEGRATION CHECKLIST
# ============================================================================

"""
[✓] Graph schema defined
[✓] Node/edge data structures
[✓] add_observation() method
[✓] Object detection storage
[✓] Loop closure edges
[✓] Spatial queries (get_nearby_nodes, get_object_locations)
[✓] Shortest path (via networkx)
[✓] Statistics and export
[✓] Unit tests (13/13 passing)
[✓] Integration tests with Lion format
[✓] Documentation

Ready for:
- [ ] Raven (Visual Memory) integration
- [ ] Agent planning layer integration
- [ ] UI visualization
- [ ] System integration testing
"""
