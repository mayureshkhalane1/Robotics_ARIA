# Apartment World - Complete Integration Guide

## 🏢 Overview

A fully integrated professional apartment environment with the ARIA robot, complete with realistic furniture, kitchen, living room, and searchable objects.

**Features:**
- Professional apartment layout with walls, doors, windows
- Kitchen area with fridge, cabinets, sink, oven
- Living room with sofa, armchair, table
- Bedroom area with desk
- **ARIA Robot integrated** - Blue robot with 4 motors and camera
- **3 Searchable Objects** - Cup, football, bottle
- Professional lighting (2 ceiling lights)
- Full physics enabled

## 🤖 Robot Configuration

### Position & Properties
- **Start Position:** (-5, -2, 0.1)
- **Size:** 0.4 × 1.2 × 0.3 meters
- **Color:** Blue
- **Mass:** 5 kg
- **Motors:** 4 independent wheel motors (wheel_fl_motor, wheel_fr_motor, wheel_bl_motor, wheel_br_motor)
- **Camera:** 320×240 resolution, mounted at height 0.9m, 0.8 radian FOV

### Camera Specifications
- **Resolution:** 320×240 pixels
- **Field of View:** 0.8 radians (≈45.8 degrees)
- **Near Plane:** 0.01m
- **Far Plane:** 50m
- **Frame Rate:** 15 FPS

## 🎯 Searchable Objects

### Cup
- **Location:** (-1.5, -5, 0.8)
- **Color:** Yellow
- **Shape:** Cylinder (Ø0.08, H0.15)
- **Mass:** 0.2 kg
- **Physics:** Enabled
- **Search Command:** "find cup"

### Football
- **Location:** (-5.5, -3.5, 0.1)
- **Color:** Brown/Orange
- **Shape:** Elongated box
- **Size:** 0.12 × 0.08 × 0.25
- **Mass:** 0.4 kg
- **Physics:** Enabled
- **Search Command:** "find football"

### Bottle
- **Location:** (-7, -0.8, 0.8)
- **Color:** Blue
- **Shape:** Cylinder (Ø0.06, H0.25)
- **Mass:** 0.3 kg
- **Physics:** Enabled
- **Search Command:** "find bottle"

## 🏗️ Apartment Layout

### Kitchen Area
- **Fridge** (Red) - Position: (-0.52, -0.5, 0)
- **Cabinets** (Dark wood) - Multiple units
- **Oven** - Integrated stove
- **Sink** - Kitchen counter
- **Worktops** - Multiple surfaces
- **Cans on table** - Yellow cans (decorative)

### Living Room Area
- **Sofa** (Dark gray) - Large seating
- **Armchair** (Dark gray) - Single seat
- **Table** (Wood) - Dining table with 4 chairs
- **Carpet** (Dark gray) - Area rug
- **Television** - Living room entertainment
- **Paintings** - Wall decorations

### Bedroom Area
- **Desk** (Wood) - Work/study area
- **Wooden Chair** - Desk chair
- **Books** - On desk and shelves

### Storage/Corridors
- **Cabinet Shelves** - Multiple storage units
- **Potted Tree** - Plant decoration
- **Flowers** - Bunch of sunflowers

## 🔍 Environment Features

### Lighting
- **Ceiling Light 1** at (-1.3341, -2.4706, 2.4) - Intensity: 5
- **Ceiling Light 2** at (-7.1011, -2.4432, 2.4) - Intensity: 8
- **Floor Light** at (-4.0043, -0.7456, 0) - Intensity: 2
- **Overall:** Well-lit environment suitable for vision tasks

### Walls & Doors
- **Multiple walls** defining apartment rooms
- **2 Doors** - Entrance and bedroom access
- **2 Windows** - Natural light sources
- **Clear pathways** for robot navigation

### Floor & Ceiling
- **Floor:** Parquetry texture (wood appearance)
- **Size:** 9.9 × 6.6 meters
- **Ceiling:** Gray textured material at 2.4m height

## 🚀 How to Use

### 1. Start Webots
```bash
./scripts/run_webots.sh
```

### 2. Load Apartment World
```
File → Open World → src/webots/worlds/apartment.wbt
```

You should see:
- Professional apartment with furniture
- Blue robot in living room area (-5, -2)
- Yellow cup on dining table
- Brown football on floor
- Blue bottle on kitchen counter
- Bright, well-lit environment

### 3. Start ARIA Agent
```bash
uv run python -m src.ui.server
```

### 4. Search for Objects
Open browser: http://127.0.0.1:8080

**Example searches:**
- Goal: `"find cup"` → Yellow cup on dining table
- Goal: `"find football"` → Brown football on floor
- Goal: `"find bottle"` → Blue bottle in kitchen
- Goal: `"explore kitchen"` → Search kitchen area
- Goal: `"go to living room"` → Navigate to sofa area

**Settings:**
- Policy: `"smart vision (VLM)"`
- Model: `"qwen3:8b"`
- Steps: `50` (to explore apartment)
- Click: **RUN**

## 📊 File Information

- **File:** `src/webots/worlds/apartment.wbt`
- **Format:** VRML R2025a
- **Lines:** 801 (includes robot + 3 objects)
- **Total Objects:** 25+ (robot + furniture + interactive objects)
- **Physics:** Enabled
- **Status:** Ready for simulation

## 🎯 Test Scenarios

### Scenario 1: Find Cup
1. Goal: `"find cup"`
2. Expected: Robot searches dining area, finds yellow cup
3. Success: Agent locates cup on table within 20 steps

### Scenario 2: Object Collection
1. Goal: `"find cup and football"`
2. Expected: Robot searches for both objects
3. Success: Agent locates both items

### Scenario 3: Apartment Exploration
1. Goal: `"explore the apartment"`
2. Expected: Robot systematically explores rooms
3. Success: Agent maps out major areas

### Scenario 4: Kitchen Search
1. Goal: `"find bottle in kitchen"`
2. Expected: Robot navigates to kitchen area
3. Success: Agent locates blue bottle

## 🔧 Technical Details

### World Configuration
- **Time Step:** 16ms
- **Gravity:** 9.81 m/s² (standard)
- **Coordinates:** VRML standard
- **Physics Solver:** Default (ODE)
- **Collision Detection:** Enabled

### Robot Motors
All motors have:
- **Max Velocity:** 10 rad/s
- **Max Torque:** 20 N⋅m
- **Type:** RotationalMotor
- **Control:** Individual motor control

### Searchable Object Properties
All searchable objects have:
- **Physics:** Enabled (mass-based)
- **Bounding Objects:** Defined for collision
- **Named:** True (identifiable by agents)
- **Visual Distinction:** Different colors

## 📸 Camera Capabilities

### What the Robot Can See
- **Kitchen area** with appliances and counter
- **Dining table** with cup and chairs
- **Living room** with sofa and armchair
- **Bedroom area** through open spaces
- **Floor objects** like football and bottles
- **Walls, doors, windows** for navigation

### Field of View
- **Horizontal Coverage:** ~45.8 degrees
- **Vertical Coverage:** ~34.2 degrees
- **Effective Range:** 0.01m to 50m
- **Resolution:** 320×240 pixels

## 🎨 Visual Features

### Colors & Appearances
- **Robot:** Blue (easily identifiable)
- **Cup:** Yellow (high contrast)
- **Football:** Brown/orange (distinct)
- **Bottle:** Blue (visually distinct)
- **Furniture:** Dark wood/gray (realistic)
- **Walls:** Light gray (neutral background)

### Lighting Quality
- Good overall illumination
- Multiple light sources
- Natural-looking shadows
- Suitable for YOLO detection
- Good color contrast

## 🔌 Integration Points

### Motor Control
```python
# Motor names for agent control
wheel_fl_motor  # Front-left wheel
wheel_fr_motor  # Front-right wheel
wheel_bl_motor  # Back-left wheel
wheel_br_motor  # Back-right wheel
```

### Camera Access
```python
# Camera parameters
camera_name: "main_camera"
resolution: (320, 240)
fieldOfView: 0.8
```

### Object Detection
```python
# Searchable object names
"cup"       # Yellow cylinder on table
"football"  # Brown box on floor
"bottle"    # Blue cylinder in kitchen
```

## ⚠️ Important Notes

1. **Robot Starting Position:** (-5, -2, 0.1) in living room area
2. **World Dimensions:** 9.9 × 6.6 meters apartment
3. **Ceiling Height:** 2.4 meters
4. **Physics:** Fully enabled - objects fall, collide
5. **Navigation:** All rooms accessible, no locked doors

## 🚧 Customization Ideas

- Add more objects to find (books, plants, etc.)
- Create multiple robots for comparison
- Add dynamic objects (moving items)
- Implement object picking/placing
- Add semantic zones (kitchen, bedroom, living)
- Create multi-agent coordination tasks

## ✅ Verification Checklist

After loading apartment.wbt:
- [ ] Window shows apartment, not black
- [ ] Blue robot visible in living room
- [ ] Yellow cup on dining table
- [ ] Brown football on floor
- [ ] Blue bottle in kitchen area
- [ ] Furniture and appliances visible
- [ ] Lighting is adequate
- [ ] Camera feed works in UI
- [ ] Robot can move (test with arrow keys)
- [ ] Objects are detectable

## 📚 Related Files

- `src/webots/worlds/apartment.wbt` - Main world file
- `src/agent/smart_vision_agent.py` - Navigation agent
- `src/perception/camera.py` - Camera module
- `src/ui/server.py` - Web dashboard
- `GETTING_STARTED.md` - Setup guide
- `SMART_VISION_GUIDE.md` - Agent documentation

## 🎓 Learning Path

**Day 1:** Load apartment, test robot movement
**Day 2:** Try basic object searches (find cup, find football)
**Day 3:** Explore multi-object searches
**Day 4:** Analyze agent reasoning in console
**Day 5:** Experiment with different policies

---

**Ready to explore the apartment?** Load apartment.wbt in Webots and start searching! 🏢🤖
