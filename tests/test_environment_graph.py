"""Unit tests and integration tests for EnvironmentGraph."""

import unittest
import time
import math
from src.agent.environment_graph import (
    EnvironmentGraph,
    GraphNode,
    Observation,
    ObjectDetection,
)


class TestEnvironmentGraph(unittest.TestCase):
    """Test suite for EnvironmentGraph."""
    
    def setUp(self):
        """Create fresh graph for each test."""
        self.graph = EnvironmentGraph(node_proximity_threshold=1.0)
    
    def test_add_observation_creates_new_node(self):
        """Adding observation at new position creates a node."""
        node_id, obs_id = self.graph.add_observation(
            position=(0.0, 0.0, 0.0),
            timestamp=time.time(),
        )
        
        self.assertIn(node_id, self.graph.nodes)
        self.assertEqual(self.graph.nodes[node_id].visit_count, 1)
        self.assertEqual(len(self.graph.nodes[node_id].observations), 1)
    
    def test_add_observation_merges_nearby_positions(self):
        """Adding observation near existing node updates it."""
        pos1 = (0.0, 0.0, 0.0)
        pos2 = (0.5, 0.3, 0.2)  # Within 1.0m threshold
        
        node_id_1, obs_id_1 = self.graph.add_observation(position=pos1)
        node_id_2, obs_id_2 = self.graph.add_observation(position=pos2)
        
        self.assertEqual(node_id_1, node_id_2)
        self.assertEqual(self.graph.nodes[node_id_1].visit_count, 2)
        self.assertEqual(len(self.graph.nodes[node_id_1].observations), 2)
    
    def test_add_object_detections(self):
        """Object detections are properly stored."""
        objects = {
            "cup": [(10, 20, 50, 60), (100, 150, 180, 200)],
            "chair": [(200, 300, 400, 500)],
        }
        
        node_id, obs_id = self.graph.add_observation(
            position=(1.0, 2.0, 3.0),
            objects_detected=objects,
        )
        
        node = self.graph.nodes[node_id]
        self.assertIn("cup", node.objects_seen)
        self.assertIn("chair", node.objects_seen)
        self.assertEqual(len(node.objects_seen["cup"]), 2)
        self.assertEqual(len(node.objects_seen["chair"]), 1)
    
    def test_get_object_locations(self):
        """Retrieve all locations where object was detected."""
        self.graph.add_observation((0.0, 0.0, 0.0), objects_detected={"cup": [(10, 20, 50, 60)]})
        self.graph.add_observation((5.0, 0.0, 0.0), objects_detected={"cup": [(15, 25, 55, 65)]})
        self.graph.add_observation((10.0, 0.0, 0.0), objects_detected={"chair": [(100, 100, 200, 200)]})
        
        cup_locations = self.graph.get_object_locations("cup")
        self.assertEqual(len(cup_locations), 2)
        
        chair_locations = self.graph.get_object_locations("chair")
        self.assertEqual(len(chair_locations), 1)
    
    def test_get_nearby_nodes(self):
        """Query nodes within radius."""
        self.graph.add_observation((0.0, 0.0, 0.0))
        self.graph.add_observation((2.0, 0.0, 0.0))
        self.graph.add_observation((10.0, 0.0, 0.0))
        
        nearby = self.graph.get_nearby_nodes((0.0, 0.0, 0.0), radius=3.0)
        self.assertEqual(len(nearby), 2)  # Node at 0.0 (distance 0) and node at 2.0
        self.assertAlmostEqual(nearby[0][1], 0.0)  # First is self
        self.assertAlmostEqual(nearby[1][1], 2.0)  # Second is 2m away
    
    def test_connect_nearby_nodes(self):
        """Auto-connect nearby nodes."""
        self.graph.add_observation((0.0, 0.0, 0.0))
        self.graph.add_observation((1.5, 0.0, 0.0))
        self.graph.add_observation((10.0, 0.0, 0.0))
        
        edges_added = self.graph.connect_nearby_nodes(max_distance=3.0)
        self.assertEqual(edges_added, 2)  # Bidirectional edge
        self.assertEqual(len(self.graph.edges), 2)
    
    def test_loop_closure(self):
        """Add loop closure edge when revisiting location."""
        node_id_1, obs_id_1 = self.graph.add_observation((0.0, 0.0, 0.0))
        node_id_2, obs_id_2 = self.graph.add_observation((5.0, 0.0, 0.0))
        
        # Simulate revisiting same location as obs_1 - far enough to create new node
        node_id_3, obs_id_3 = self.graph.add_observation((10.0, 0.0, 0.0))
        
        # Register loop closure between obs_1 and obs_3 (which are in different nodes)
        success = self.graph.add_loop_closure(obs_id_1, obs_id_3)
        self.assertTrue(success)
        self.assertGreater(len(self.graph.edges), 0)
    
    def test_statistics(self):
        """Graph statistics are accurate."""
        self.graph.add_observation((0.0, 0.0, 0.0), objects_detected={"cup": [(10, 20, 50, 60)]})
        self.graph.add_observation((2.0, 0.0, 0.0), objects_detected={"cup": [(15, 25, 55, 65)], "chair": [(100, 100, 200, 200)]})
        
        stats = self.graph.get_statistics()
        self.assertEqual(stats["num_nodes"], 2)
        self.assertEqual(stats["num_observations"], 2)
        self.assertEqual(stats["num_object_detections"], 3)
        self.assertEqual(stats["unique_object_classes"], 2)
    
    def test_distance_calculation(self):
        """Distance calculations are correct."""
        dist = self.graph._distance_3d((0, 0, 0), (3, 4, 0))
        self.assertAlmostEqual(dist, 5.0)  # 3-4-5 triangle
    
    def test_export_json(self):
        """Graph can be exported to JSON."""
        import tempfile
        import os
        import json
        
        self.graph.add_observation((0.0, 0.0, 0.0))
        self.graph.add_observation((2.0, 0.0, 0.0))
        
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "graph.json")
            success = self.graph.export_json(filepath)
            self.assertTrue(success)
            
            with open(filepath) as f:
                data = json.load(f)
            self.assertIn("nodes", data)
            self.assertIn("edges", data)
            self.assertIn("statistics", data)
    
    def test_to_dict(self):
        """Graph serialization to dict."""
        self.graph.add_observation((0.0, 0.0, 0.0))
        
        data = self.graph.to_dict()
        self.assertIn("nodes", data)
        self.assertIn("edges", data)
        self.assertIn("statistics", data)


class TestIntegrationWithDetections(unittest.TestCase):
    """Test integration with detection output from Lion (object detector)."""
    
    def setUp(self):
        """Create graph and simulate detection pipeline."""
        self.graph = EnvironmentGraph()
    
    def test_add_detections_from_lion_format(self):
        """Consume detection format from object detector (Lion)."""
        # Simulate Lion's output format:
        # {
        #   "detections": [
        #     {"class": "cup", "confidence": 0.92, "bbox": [x1,y1,x2,y2]},
        #     ...
        #   ],
        #   "timestamp": float,
        #   "camera_id": "webots_camera_0"
        # }
        
        lion_output = {
            "detections": [
                {"class": "cup", "confidence": 0.92, "bbox": (50, 60, 100, 150)},
                {"class": "table", "confidence": 0.85, "bbox": (10, 20, 200, 200)},
            ],
            "timestamp": time.time(),
            "camera_id": "webots_camera_0",
        }
        
        # Convert to format for graph
        objects_detected = {}
        for det in lion_output["detections"]:
            class_name = det["class"]
            bbox = tuple(det["bbox"])
            if class_name not in objects_detected:
                objects_detected[class_name] = []
            objects_detected[class_name].append(bbox)
        
        # Robot position (from Shark's frame metadata)
        robot_position = (1.0, 2.0, 0.0)
        
        node_id, obs_id = self.graph.add_observation(
            position=robot_position,
            timestamp=lion_output["timestamp"],
            objects_detected=objects_detected,
            confidence=0.9,
        )
        
        # Verify
        node = self.graph.nodes[node_id]
        self.assertIn("cup", node.objects_seen)
        self.assertIn("table", node.objects_seen)
        self.assertEqual(len(node.objects_seen["cup"]), 1)
        self.assertEqual(len(node.objects_seen["table"]), 1)
    
    def test_temporal_sequence(self):
        """Simulate robot moving through environment with detections."""
        trajectory = [
            (0.0, 0.0, 0.0, {"cup": [(50, 60, 100, 150)]}),
            (1.0, 0.0, 0.0, {"cup": [(55, 65, 105, 155)]}),
            (2.0, 0.0, 0.0, {"table": [(10, 20, 200, 200)]}),
            (3.0, 0.0, 0.0, {}),  # No objects
            (4.0, 0.0, 0.0, {"cup": [(45, 55, 95, 145)]}),  # Cup seen again
        ]
        
        node_ids = []
        for x, y, z, objects in trajectory:
            node_id, obs_id = self.graph.add_observation(
                position=(x, y, z),
                objects_detected=objects if objects else None,
            )
            node_ids.append(node_id)
        
        # Verify graph structure
        self.assertEqual(len(self.graph.nodes), 5)  # All separate nodes
        self.assertEqual(self.graph.get_statistics()["num_observations"], 5)
        
        # Verify cup was seen in multiple locations
        cup_locs = self.graph.get_object_locations("cup")
        self.assertEqual(len(cup_locs), 3)
        
        # Verify table
        table_locs = self.graph.get_object_locations("table")
        self.assertEqual(len(table_locs), 1)


if __name__ == "__main__":
    unittest.main()
