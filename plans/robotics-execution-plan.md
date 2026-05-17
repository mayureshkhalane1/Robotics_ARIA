# Robotics Project Execution Plan: Sim-plicity
## Mobile Robot Challenge - Visual Object Following

**Project**: Autonomous mobile robot that follows objects using only RGB camera
**Team**: Sim-plicity (You're solo executing)
**Key Dates**: 
- Proposal Presentation: March 13 or 20, 2026 (5 min, due 2026-03-10)
- Live Demo: May 1, 2026
- Final Submission: May 11, 2026

---

## Context

You are the sole implementer for a mobile robotics project that requires building a complete autonomous vision-based object tracking system. The project has two challenges:
1. **Challenge I**: Follow a known object along a self-designed trajectory
2. **Challenge II**: Follow an unknown object along a pre-determined trajectory with obstacles

Both challenges use **ONLY RGB camera input** (no ultrasound or other sensors), making this a pure computer vision + control problem. You have ~2 months to learn the robot platform, implement vision algorithms, integrate with robot control, and deliver working code plus technical documentation.

---

## Phase 1: Foundation & Learning (Weeks 1-2)
**Goal**: Understand the robot platform and establish development environment

### 1.1 Robot Platform Setup
- [ ] Identify the exact robot model used (likely TurtleBot, JetBot, or similar)
- [ ] Access robot documentation and SDK
- [ ] Set up development environment (Python 3.x, ROS if applicable)
- [ ] Verify robot communication (USB, network, etc.)
- [ ] Test basic motor control and camera access
- [ ] Document camera specs: resolution, FPS, lens characteristics

### 1.2 Computer Vision Foundations
- [ ] Review OpenCV basics for Python (if not already familiar)
- [ ] Understand color space conversions (RGB, HSV, LAB)
- [ ] Learn about contour detection and morphological operations
- [ ] Study object detection approaches:
  - [ ] Color-based detection (simplest, good for controlled lighting)
  - [ ] Template matching (if object shape is known)
  - [ ] Edge detection and shape descriptors
  - [ ] Optional: YOLO/MobileNet (if you want advanced detection)

### 1.3 Control & Navigation Basics
- [ ] Understand robot kinematics (differential drive vs other)
- [ ] Learn basic movement control (motor PWM, velocity commands)
- [ ] Study trajectory following (PID control for velocity/heading)
- [ ] Review distance-keeping algorithms (proportional control)

### Deliverables for Phase 1
- [ ] Robot boots and responds to test commands
- [ ] Camera stream accessible in Python
- [ ] Simple test script: detect colored object in frame

---

## Phase 2: Algorithm Development (Weeks 3-4)
**Goal**: Implement core algorithms independently and test with robot

### 2.1 Object Detection Pipeline
Build a modular detection system:
- [ ] **Input stage**: Read camera frames, handle frame timing
- [ ] **Preprocessing**: Color space conversion, noise reduction if needed
- [ ] **Detection algorithm**: Implement 1-2 detection methods:
  - [ ] Color range detection (HSV thresholding) - START HERE, fastest iteration
  - [ ] Contour analysis for centroid/shape
  - [ ] (Optional) Template matching if object is rigid
- [ ] **Output stage**: Return object position (x, y) and size
- [ ] Test in various lighting conditions before moving to robot

### 2.2 Object Tracking Pipeline
- [ ] Implement centroid tracking across frames
- [ ] Handle missing detections (predict next position)
- [ ] Calculate object velocity and distance from camera
- [ ] Smooth detected positions (Kalman filter or moving average)
- [ ] Determine when object is lost/reappeared

### 2.3 Distance Estimation
- [ ] Use object size in frame to estimate distance (if object size known)
- [ ] Calibrate: map pixel size → real-world distance
- [ ] Handle size variation due to rotation (object dragged on floor)
- [ ] Test accuracy by measuring actual vs estimated distances

### 2.4 Robot Control Layer
- [ ] Implement motor control wrapper (velocity commands)
- [ ] Create trajectory follower:
  - [ ] Linear motion to target heading
  - [ ] Heading correction (yaw angle to object)
  - [ ] Distance maintenance (approach/retreat logic)
- [ ] Test control on stationary object first
- [ ] Tune PID gains for smooth movement

### Deliverables for Phase 2
- [ ] Object detection working on robot camera (>80% accuracy in test environment)
- [ ] Tracking is smooth with <100ms latency
- [ ] Robot can maintain distance from stationary object
- [ ] Code is modular: `detect.py`, `track.py`, `control.py`

---

## Phase 3: Challenge Implementation (Weeks 5-6)
**Goal**: Build complete solutions for both challenges

### 3.1 Challenge I: Known Object, Custom Trajectory
- [ ] Design a simple trajectory (circle, figure-8, or complex shape)
- [ ] Document: "object will move from point A → B → C → home"
- [ ] Implement Challenge I:
  - [ ] Robot detects object at home position
  - [ ] Robot follows object as it's dragged along your planned trajectory
  - [ ] Robot returns object to home position
- [ ] Test with human dragging object (or controlled pull mechanism)
- [ ] Iterate on control smoothness
- [ ] Video record successful run

### 3.2 Challenge II: Unknown Object, Given Trajectory
- [ ] Study the challenge spec: trajectory with 2 large fixed obstacles
- [ ] Implement Challenge II:
  - [ ] Robot must detect and follow unknown object
  - [ ] Robot navigates around fixed obstacles
  - [ ] Object follows a pre-drawn path on floor
- [ ] Key: ensure your algorithm is general (works with different object colors)
- [ ] Test with various objects (different colors/sizes)
- [ ] Video record successful run

### 3.3 Robustness Testing
- [ ] Test in different lighting conditions (shadows, glare)
- [ ] Test with object partially obscured
- [ ] Test recovery if object temporarily lost
- [ ] Stress test: fast movements, sharp turns
- [ ] Document failure modes and limitations

### Deliverables for Phase 3
- [ ] Challenge I working end-to-end
- [ ] Challenge II working end-to-end
- [ ] Video of each challenge (~30s-1min)
- [ ] Complete source code with clear structure
- [ ] Ability to reproduce results

---

## Phase 4: Technical Report & Documentation (Week 7)
**Goal**: Communicate methods and results clearly for grading

### 4.1 Technical Report (max 4 pages)
Write in scientific style covering:
- [ ] **Title & Authors**: "Visual Object Tracking for Mobile Robot Navigation using RGB Camera"
- [ ] **Introduction**: Problem statement, why it's interesting, related work
- [ ] **Methods** (main section):
  - [ ] Object detection approach: why chosen, how it works
  - [ ] Tracking mechanism: centroid tracking, Kalman filtering, etc.
  - [ ] Distance estimation: calibration method, accuracy
  - [ ] Robot control: PID tuning, movement constraints
- [ ] **Results**: Performance metrics
  - [ ] Detection accuracy (%)
  - [ ] Tracking smoothness (error from center)
  - [ ] Distance error (cm)
  - [ ] Challenge completion rate
- [ ] **Challenges & Limitations**: What didn't work, why
- [ ] **References**: Papers/libraries used (cite the research paper you have)
- [ ] **Appendix A**: Dependencies & Setup
  - [ ] List all libraries: opencv-python, numpy, etc.
  - [ ] Robot SDK version
  - [ ] Installation commands
  - [ ] How to run: `python main.py --challenge 1`

### 4.2 Code Documentation
- [ ] Add docstrings to all functions
- [ ] README.md with:
  - [ ] Project overview
  - [ ] Architecture diagram (text or simple)
  - [ ] Quick start instructions
  - [ ] Performance notes
- [ ] Well-organized directory structure:
  ```
  sim-plicity/
  ├── src/
  │   ├── detect.py        (object detection)
  │   ├── track.py         (tracking)
  │   ├── control.py       (robot control)
  │   └── main.py          (challenge logic)
  ├── calibration/         (calibration data, images)
  ├── tests/               (test scripts)
  ├── README.md
  ├── requirements.txt
  └── technical_report.pdf
  ```

### Deliverables for Phase 4
- [ ] 4-page technical report in PDF
- [ ] Well-commented source code
- [ ] README and setup instructions
- [ ] All files zipped and ready for submission

---

## Phase 5: Proposal Presentation (Due March 10)
**Goal**: Get feedback and clarify approach

### 5.1 5-Minute Presentation (5 slides)
1. **Title & Team Members**: Introduce team, your sole execution plan
2. **Goal & Novelty**: What's novel?
   - Robust detection in uncontrolled lighting
   - Smooth trajectory following without pre-mapping
   - Adaptability to unknown objects
   - Reference the research paper you have (LLMs for autonomous mapping/navigation)
3. **How You'll Pursue Goals**:
   - Phase breakdown
   - Technologies: OpenCV, ROS/robot SDK, Python
   - Timeline
4. **Challenges & Risks**:
   - Lighting variation → solution: adaptive color detection + fallback
   - Object occlusion → solution: motion prediction
   - Robot precision → solution: PID tuning, encoder feedback if available
   - Tight timeline with solo execution → solution: prioritize core features first
5. **Deliverables** (May 18-19):
   - Working source code
   - Video of Challenge I
   - Technical report

### Deliverables for Phase 5
- [ ] 5-slide presentation deck
- [ ] Ready to present (public speaking practice)

---

## Phase 6: Final Push & Polish (Week 8)
**Goal**: Refinement, testing, and final deliverables

### 6.1 Performance Tuning
- [ ] Benchmark: measure latency (frame capture → command output)
- [ ] Optimize: aim for <200ms round-trip
- [ ] Test with various object colors (prepare for Challenge II variety)
- [ ] Stress test: can your code handle 30+ FPS sustained?

### 6.2 Failsafes & Recovery
- [ ] Handle lost detection: robot stops safely
- [ ] Timeout logic: if no object seen for N frames, alert
- [ ] Emergency stop mechanism
- [ ] Graceful shutdown

### 6.3 Final Testing & Video
- [ ] Run Challenge I 5 times, pick best video
- [ ] Run Challenge II 5 times, pick best video
- [ ] Create short demo video (30-60s per challenge)
- [ ] Include narration if helpful

### 6.4 Final Submission (Due May 11)
- [ ] Source code (well-organized, commented)
- [ ] Challenge I video
- [ ] Technical report
- [ ] Appendix with setup/execution instructions
- [ ] All zipped for Brightspace

---

## Critical Success Factors

1. **Start early on robot familiarization**: Don't underestimate setup time
2. **Build modular code**: Decouple detection, tracking, and control
3. **Test components independently**: Don't wait until everything is "done"
4. **Document as you go**: Writing the report will be much easier with notes
5. **Plan conservative**: Aim for 80% completion by May 1 (live demo)
6. **Prioritize Challenge I first**: It's simpler, success here gives confidence
7. **Use version control**: Git commit working versions before major refactors

---

## Timeline at a Glance

| Week | Focus | Key Deliverables |
|------|-------|------------------|
| 1-2  | Robot setup + vision fundamentals | Working camera feed, basic detection |
| 3-4  | Core algorithms | Modular detect/track/control modules |
| 5-6  | Integration + challenges | Both challenges working end-to-end |
| 7    | Documentation | Technical report, code cleanup |
| ~8   | Polish + final submission | Videos, zipped deliverables |

**Presentation**: By March 10 (5 slides, 5 min)
**Live Demo**: May 1, 2026
**Final Submission**: May 11, 2026

---

## Resources to Gather

- [ ] Robot documentation (user manual, SDK)
- [ ] OpenCV + Python tutorials
- [ ] Research paper you have: "Leveraging Large Language Models for Autonomous Robotic Mapping and Navigation" (consider how LLM-based planning could enhance your solution)
- [ ] ROS tutorials (if robot uses ROS)
- [ ] PID control tutorials for robotics
- [ ] Color detection in HSV space examples

---

## Questions to Clarify

Before diving in, verify:
1. **Robot platform**: What exact model? (TurtleBot 3, JetBot, custom?)
2. **Development environment**: Where will you run code? (laptop + SSH to robot, or on-robot?)
3. **Camera specs**: Resolution, FPS, any calibration data available?
4. **Testing space**: Where will you test? (lab, open room? lighting conditions?)
5. **Object choice for Challenge I**: Any constraints? (size, weight, color?)
6. **Your background**: Comfort level with Python, OpenCV, robotics?

---

## Success Metrics

**By March 13**: Proposal presented, approach approved by instructors
**By May 1 (live demo)**: Both challenges pass successfully
**By May 11**: All deliverables submitted, technical report clear and complete
**Grading**:
- Originality of detection/control approach
- Smoothness and robustness of motion
- Code quality and documentation
- Technical report clarity
- Video demonstration quality
