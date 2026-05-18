"""Environment graph - spatial mapping of explored areas and detected objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import networkx as nx
import numpy as np


@dataclass
class Node:
    """A node in the environment graph representing a location."""

    node_id: str
    pose: dict  # {x, y, z, rotation}
    timestamp: float
    observation_ids: list[str] = field(default_factory=list)
    objects_seen: dict[str, list[dict]] = field(default_factory=dict)  # class -> detections
    visited_count: int = 1
    is_frontier: bool = False  # True if unexplored area nearby


@dataclass
class Edge:
    """An edge in the environment graph."""

    from_id: str
    to_id: str
    distance: float
    traversable: bool = True
    traversal_count: int = 0


class EnvironmentGraph:
    """Graph-based spatial representation of explored environment.
    
    Features:
    - Node creation/merging based on position proximity
    - Object detection storage and retrieval
    - Loop closure detection for revisited locations
    - Shortest path finding
    - Frontier/exploration planning
    - Graph export for visualization
    """

    def __init__(self, merge_threshold: float = 0.5):
        """Initialize environment graph.

        Args:
            merge_threshold: Distance (meters) to consider as same location
        """
        self.graph = nx.Graph()
        self.nodes_dict: dict[str, Node] = {}
        self.merge_threshold = merge_threshold
        self.node_counter = 0
        self.loop_closures: list[tuple[str, str]] = []  # Track loop closure edges

    def add_observation(
        self,
        pose: dict,
        timestamp: float,
        observation_id: str,
        objects_detected: Optional[list[dict]] = None,
    ) -> str:
        """Add observation to graph (creates or merges node).

        Args:
            pose: Robot pose {x, y, z, rotation}
            timestamp: Observation timestamp
            observation_id: ID from visual memory
            objects_detected: List of detected objects

        Returns:
            Node ID (new or existing)
        """
        objects_detected = objects_detected or []

        # Check if close to existing node
        nearest_node_id = self._find_nearest_node(pose)

        if nearest_node_id:
            # Merge with existing node
            node = self.nodes_dict[nearest_node_id]
            node.observation_ids.append(observation_id)
            node.visited_count += 1
            node.timestamp = timestamp  # Update timestamp

            # Merge objects
            for obj in objects_detected:
                class_name = obj.get("class_name", "unknown")
                if class_name not in node.objects_seen:
                    node.objects_seen[class_name] = []
                node.objects_seen[class_name].append(obj)

            return nearest_node_id

        else:
            # Create new node
            node_id = f"node_{self.node_counter}"
            self.node_counter += 1

            node = Node(
                node_id=node_id,
                pose=pose,
                timestamp=timestamp,
                observation_ids=[observation_id],
                objects_seen={},
            )

            # Add objects
            for obj in objects_detected:
                class_name = obj.get("class_name", "unknown")
                node.objects_seen[class_name] = [obj]

            # Add to graph
            self.graph.add_node(
                node_id,
                pose=pose,
                timestamp=timestamp,
                observation_ids=[observation_id],
            )
            self.nodes_dict[node_id] = node

            return node_id

    def _find_nearest_node(self, pose: dict, search_radius: float = None) -> Optional[str]:
        """Find nearest existing node within threshold distance.

        Args:
            pose: Query pose
            search_radius: Search radius (default: merge_threshold)

        Returns:
            Node ID or None
        """
        if not self.nodes_dict:
            return None

        search_radius = search_radius or self.merge_threshold

        nearest_id = None
        nearest_dist = float("inf")

        for node_id, node in self.nodes_dict.items():
            dist = self._pose_distance(pose, node.pose)
            if dist < nearest_dist and dist < search_radius:
                nearest_dist = dist
                nearest_id = node_id

        return nearest_id

    def add_edge(
        self, node1_id: str, node2_id: str, distance: float, traversable: bool = True
    ) -> None:
        """Add edge between nodes.

        Args:
            node1_id: First node ID
            node2_id: Second node ID
            distance: Distance between nodes
            traversable: Whether edge is traversable
        """
        if node1_id not in self.nodes_dict or node2_id not in self.nodes_dict:
            return

        self.graph.add_edge(
            node1_id,
            node2_id,
            weight=distance,
            traversable=traversable,
            traversal_count=0,
        )

    def get_nearest_nodes(self, pose: dict, radius: float = 2.0) -> list[Node]:
        """Get nodes within radius of pose.

        Args:
            pose: Query pose
            radius: Search radius in meters

        Returns:
            List of nearby nodes (sorted by distance)
        """
        nearby = []

        for node in self.nodes_dict.values():
            dist = self._pose_distance(pose, node.pose)
            if dist <= radius:
                nearby.append((node, dist))

        # Sort by distance
        nearby.sort(key=lambda x: x[1])

        return [node for node, _ in nearby]

    def get_object_locations(self, object_name: str) -> list[dict]:
        """Find all nodes where object was detected.

        Args:
            object_name: Name of object (e.g., "cup")

        Returns:
            List of dicts with {node_id, pose, detections}
        """
        locations = []
        object_name = object_name.lower().strip()

        for node_id, node in self.nodes_dict.items():
            for class_name, detections in node.objects_seen.items():
                if class_name.lower() == object_name:
                    locations.append(
                        {
                            "node_id": node_id,
                            "pose": node.pose,
                            "detections": detections,
                            "visited_count": node.visited_count,
                        }
                    )

        return locations

    def path_to_unexplored(self) -> Optional[list[dict]]:
        """Find path to nearest unexplored/frontier area.

        Returns:
            List of waypoints or None
        """
        # Find frontier nodes (unvisited or rarely visited)
        frontier_nodes = [
            node_id
            for node_id, node in self.nodes_dict.items()
            if node.is_frontier or node.visited_count == 1
        ]

        if not frontier_nodes:
            # No clear frontier, return a random unvisited area
            unvisited = [node_id for node_id in self.graph.nodes() if node_id in self.nodes_dict]
            if unvisited:
                frontier_nodes = [unvisited[0]]

        if not frontier_nodes:
            return None

        # Try to find path to first frontier
        target = frontier_nodes[0]
        target_pose = self.nodes_dict[target].pose

        return [target_pose]

    def get_node(self, node_id: str) -> Optional[Node]:
        """Get node by ID.

        Args:
            node_id: Node ID

        Returns:
            Node or None
        """
        return self.nodes_dict.get(node_id)

    def get_all_nodes(self) -> list[Node]:
        """Get all nodes in graph.

        Returns:
            List of nodes
        """
        return list(self.nodes_dict.values())

    def export_to_dict(self) -> dict:
        """Export graph as dictionary for visualization/analysis.

        Returns:
            Dict with nodes and edges
        """
        nodes_list = []
        for node in self.nodes_dict.values():
            nodes_list.append(
                {
                    "id": node.node_id,
                    "pose": node.pose,
                    "visited_count": node.visited_count,
                    "objects_seen": {k: len(v) for k, v in node.objects_seen.items()},
                }
            )

        edges_list = []
        for u, v, data in self.graph.edges(data=True):
            edges_list.append(
                {
                    "from": u,
                    "to": v,
                    "distance": data.get("weight", 0),
                    "traversable": data.get("traversable", True),
                }
            )

        return {
            "nodes": nodes_list,
            "edges": edges_list,
            "total_nodes": len(nodes_list),
            "total_edges": len(edges_list),
        }

    def get_stats(self) -> dict:
        """Get graph statistics.

        Returns:
            Dict with stats
        """
        return {
            "total_nodes": len(self.nodes_dict),
            "total_edges": self.graph.number_of_edges(),
            "unique_objects": self._count_unique_objects(),
            "frontier_nodes": sum(1 for n in self.nodes_dict.values() if n.is_frontier),
        }

    def _count_unique_objects(self) -> int:
        """Count unique object types seen."""
        unique_objects = set()
        for node in self.nodes_dict.values():
            unique_objects.update(node.objects_seen.keys())
        return len(unique_objects)

    @staticmethod
    def _pose_distance(pose1: dict, pose2: dict) -> float:
        """Calculate Euclidean distance between poses.

        Args:
            pose1: First pose {x, y, z, ...}
            pose2: Second pose

        Returns:
            Distance in meters
        """
        dx = pose1.get("x", 0) - pose2.get("x", 0)
        dy = pose1.get("y", 0) - pose2.get("y", 0)
        dz = pose1.get("z", 0) - pose2.get("z", 0)

        return np.sqrt(dx**2 + dy**2 + dz**2)

    def add_loop_closure(self, obs_id_1: str, obs_id_2: str) -> bool:
        """Register loop closure when same location is revisited.
        
        Called by visual memory when it detects same visual appearance
        in two different observations.
        
        Args:
            obs_id_1: First observation ID
            obs_id_2: Second observation ID (same visual location)
        
        Returns:
            True if loop closure added, False if obs IDs not found
        """
        # Find nodes containing these observations
        node_1_id = None
        node_2_id = None
        
        for node_id, node in self.nodes_dict.items():
            if obs_id_1 in node.observation_ids:
                node_1_id = node_id
            if obs_id_2 in node.observation_ids:
                node_2_id = node_id
        
        if not node_1_id or not node_2_id or node_1_id == node_2_id:
            return False
        
        # Add edge representing loop closure
        node_1 = self.nodes_dict[node_1_id]
        node_2 = self.nodes_dict[node_2_id]
        distance = self._pose_distance(node_1.pose, node_2.pose)
        
        self.graph.add_edge(
            node_1_id,
            node_2_id,
            weight=distance,
            traversable=True,
            loop_closure=True,
        )
        self.loop_closures.append((node_1_id, node_2_id))
        
        return True
    
    def shortest_path(self, from_node_id: str, to_node_id: str) -> Optional[list[str]]:
        """Find shortest path between two nodes using Dijkstra's algorithm.
        
        Args:
            from_node_id: Starting node ID
            to_node_id: Destination node ID
        
        Returns:
            List of node IDs forming the path, or None if no path exists
        """
        if from_node_id not in self.nodes_dict or to_node_id not in self.nodes_dict:
            return None
        
        try:
            path = nx.shortest_path(self.graph, from_node_id, to_node_id, weight="weight")
            return path
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None
    
    def get_connected_component(self, node_id: str) -> set[str]:
        """Get all nodes reachable from a given node.
        
        Args:
            node_id: Starting node ID
        
        Returns:
            Set of reachable node IDs
        """
        if node_id not in self.nodes_dict:
            return {node_id} if node_id in self.nodes_dict else set()
        
        if len(self.graph) == 0:
            return {node_id}
        
        return set(nx.node_connected_component(self.graph.to_undirected(), node_id))
    
    def connect_nearby_nodes(self, max_distance: float = 3.0) -> int:
        """Auto-connect nearby nodes that aren't already connected.
        
        Args:
            max_distance: Maximum distance to consider nodes adjacent (meters)
        
        Returns:
            Number of edges added
        """
        edges_added = 0
        node_list = list(self.nodes_dict.values())
        
        for i, node_a in enumerate(node_list):
            for node_b in node_list[i + 1:]:
                distance = self._pose_distance(node_a.pose, node_b.pose)
                
                if distance < max_distance:
                    # Check if edge already exists
                    if not self.graph.has_edge(node_a.node_id, node_b.node_id):
                        traversable = distance < max_distance
                        self.graph.add_edge(
                            node_a.node_id,
                            node_b.node_id,
                            weight=distance,
                            traversable=traversable,
                            traversal_count=0,
                        )
                        edges_added += 1
        
        return edges_added

    def clear(self) -> None:
        """Clear all nodes and edges."""
        self.graph.clear()
        self.nodes_dict.clear()
        self.node_counter = 0
        self.loop_closures.clear()


# Global environment graph instance
_env_graph: Optional[EnvironmentGraph] = None


def get_environment_graph() -> EnvironmentGraph:
    """Get or create global environment graph.

    Returns:
        EnvironmentGraph instance
    """
    global _env_graph
    if _env_graph is None:
        _env_graph = EnvironmentGraph(merge_threshold=0.5)
    return _env_graph


def init_environment_graph(merge_threshold: float = 0.5) -> EnvironmentGraph:
    """Initialize environment graph.

    Args:
        merge_threshold: Distance to merge nodes

    Returns:
        EnvironmentGraph instance
    """
    global _env_graph
    _env_graph = EnvironmentGraph(merge_threshold=merge_threshold)
    return _env_graph
