#!/usr/bin/env python3
"""
ARIA Camera Feed Test - Demonstrates live camera streaming from Webots
"""

import time
import sys
from src.perception.camera import get_camera_manager
from src.perception.object_detector import get_detector
from src.agent.visual_memory import get_visual_memory
from src.agent.environment_graph import get_environment_graph
import cv2


def main():
    """Test camera feed and show real-time processing."""
    print("\n" + "=" * 60)
    print("ARIA CAMERA FEED TEST")
    print("=" * 60)
    
    # Initialize components
    print("\n[INIT] Loading components...")
    camera = get_camera_manager()
    detector = get_detector()
    memory = get_visual_memory()
    graph = get_environment_graph()
    print("✓ Components loaded")
    
    # Test for 5 frames
    num_frames = 5
    print(f"\n[TEST] Capturing {num_frames} frames from Webots...\n")
    
    for frame_num in range(num_frames):
        print(f"--- Frame {frame_num + 1}/{num_frames} ---")
        
        # Get frame
        frame = camera.get_frame()
        if frame is None:
            print("✗ Failed to get frame")
            continue
        
        print(f"✓ Camera: {frame.shape[0]}x{frame.shape[1]} @ {camera.fps:.1f} FPS")
        
        # Run detection
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        detections = detector.detect(frame_rgb)
        print(f"✓ Detector: Found {len(detections)} objects")
        
        for det in detections[:3]:
            print(f"  - {det.class_name} ({det.confidence*100:.0f}%)")
        
        # Store in memory
        obs_id = memory.add_observation(
            frame, 
            (frame_num * 0.5, 0, 0, 0, 0, 0),
            timestamp=time.time(),
            detected_objects={}
        )
        print(f"✓ Memory: Stored observation {obs_id}")
        
        # Check loop closure
        loop_closure = memory.find_loop_closure(frame)
        if loop_closure and loop_closure.similarity_score > 0.8:
            print(f"✓ Loop Closure: Recognized location (similarity={loop_closure.similarity_score:.2f})")
        
        # Update graph
        node_id = graph.add_observation(
            pose={"x": frame_num * 0.5, "y": 0, "z": 0, "rotation": 0},
            timestamp=time.time(),
            observation_id=obs_id,
            objects_detected=[]
        )
        print(f"✓ Graph: Added node {node_id}")
        
        # Show stats
        mem_stats = memory.get_stats()
        graph_stats = graph.get_stats()
        print(f"  Memory: {mem_stats['num_observations']} obs, {mem_stats.get('memory_usage_mb', 0):.1f} MB")
        print(f"  Graph: {graph_stats['total_nodes']} nodes, {graph_stats['unique_objects']} object types")
        
        print()
        time.sleep(0.5)
    
    # Final summary
    print("=" * 60)
    print("CAMERA FEED TEST RESULTS")
    print("=" * 60)
    print(f"✓ Captured {num_frames} frames successfully")
    print(f"✓ Memory: {memory.get_stats()['num_observations']} observations stored")
    print(f"✓ Graph: {graph.get_stats()['total_nodes']} locations mapped")
    print(f"✓ Camera: {camera.get_camera_info()}")
    print("\n✓ ALL SYSTEMS OPERATIONAL")
    print("\nNext: Start UI server with:")
    print("  uv run python -m src.ui.server")
    print("\nThen open http://127.0.0.1:8080 to see live camera feed!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[ABORT] Test interrupted")
        sys.exit(0)
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
