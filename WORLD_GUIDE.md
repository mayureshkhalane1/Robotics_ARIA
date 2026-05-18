# Smart Home World Guide

## 🏠 World Overview

A complete, clean Webots world featuring a modern smart home with:
- **Living room** - Sofa, armchair, table, lamp, rug
- **Kitchen** - Counter, fridge, dishes
- **Bedroom** - Bed, cabinet
- **Interactive Objects** - Cup, football, plant
- **Navigation Space** - 20×20 meter arena with proper lighting

## 📍 Object Locations

### Living Room (Center Area)
| Object | Position | Size | Type |
|--------|----------|------|------|
| **Sofa** | (2, 0.4, 10) | 3×0.8×1 | Furniture |
| **Armchair** | (6, 0.35, 10) | 1.2×0.7×1.2 | Furniture |
| **Dining Table** | (4, 0.35, 6) | 2×0.7×1.5 | Furniture |
| **Chair 1** | (2.5, 0.35, 6.5) | 0.5×1×0.5 | Chair |
| **Chair 2** | (5.5, 0.35, 6.5) | 0.5×1×0.5 | Chair |
| **Lamp** | (5, 1.5, 8) | Ø0.15, H1 | Light |
| **Rug** | (4, 0.005, 8) | 3×2.5 | Texture |

### Kitchen (North Area)
| Object | Position | Size | Type |
|--------|----------|------|------|
| **Counter** | (12, 0.6, 2) | 4×1.2×1 | Furniture |
| **Fridge** | (14, 0.85, 3.5) | 0.8×1.7×0.7 | Appliance |
| **Dish** | (12.5, 1.3, 2) | Ø0.12, H0.03 | Object |

### Bedroom (East Area)
| Object | Position | Size | Type |
|--------|----------|------|------|
| **Bed** | (16, 0.5, 12) | 2×1×2.5 | Furniture |

### Storage (West Area)
| Object | Position | Size | Type |
|--------|----------|------|------|
| **Bookshelf** | (0.5, 0.85, 8) | 0.4×1.7×1.5 | Furniture |
| **Cabinet** | (1, 0.85, 18) | 1.5×1.7×0.5 | Furniture |

### Interactive Objects
| Object | Position | Name | Detectable |
|--------|----------|------|-----------|
| **Cup** | (4.5, 1.0, 6) | cup | ✓ Yellow, small |
| **Football** | (6, 0.35, 8) | football | ✓ Brown, on floor |
| **Plant** | (1, 0.5, 2) | plant | ✓ Green, cylinder |

## 🤖 Robot Properties

- **Start Position:** (1, 0.62, 1)
- **Size:** 0.4 (width) × 1.2 (height) × 0.3 (depth)
- **Color:** Blue
- **Wheels:** 4 independent motors (FL, FR, BL, BR)
- **Camera:** 320×240 resolution, mounted at height 0.9m
- **Physics:** Enabled with mass 5kg

## 🎯 Example Search Queries

### Object Discovery
```
Goal: "find cup"
Expected: Robot will search living room, detect yellow cup on table
Location: (4.5, 1.0, 6)
```

```
Goal: "find football"
Expected: Robot will search and locate brown football on floor
Location: (6, 0.35, 8)
```

```
Goal: "find plant"
Expected: Robot will locate green plant in storage area
Location: (1, 0.5, 2)
```

### Area Exploration
```
Goal: "explore living room"
Expected: Robot explores center area with furniture
Contains: Sofa, chairs, table, lamp
```

```
Goal: "go to kitchen"
Expected: Robot navigates to north area
Contains: Counter, fridge, dishes
```

```
Goal: "go to bedroom"
Expected: Robot explores east area
Contains: Bed, cabinet
```

## 🎨 Visual Features

### Lighting
- **Exterior:** Noon park empty (bright outdoor light)
- **Interior:** Good visibility throughout
- **Shadows:** Natural from top-down lighting
- **Color Palette:** Earth tones with accent colors

### Surfaces
- **Floor:** Textured tile pattern (1×1 meter tiles)
- **Walls:** Arena walls (2.5m high)
- **Furniture:** Wood, fabric, metal materials (realistic)
- **Objects:** Colored for easy visual detection

### Material Properties
| Object | BaseColor | Metalness | Roughness |
|--------|-----------|-----------|-----------|
| Robot | Blue | 0.3 | 0.4 |
| Sofa | Brown | 0.1 | 0.8 |
| Kitchen Counter | White | 0.3 | 0.4 |
| Fridge | Gray | 0.6 | 0.3 |
| Cup | Yellow | 0.4 | 0.5 |
| Football | Brown | 0.2 | 0.6 |

## 🔧 World Configuration

### Physics
- **Gravity:** 9.81 m/s² (standard Earth)
- **Solver:** Default (accurate for medium-speed robots)
- **Collision:** Enabled for all objects
- **Friction:** Physics-based per material

### Simulation
- **Time Step:** 32ms (default)
- **Speed:** Configurable (0.1x to 10x)
- **Rendering:** 1200×900 window
- **Coordinates:** NUE (North-Up-East) standard

## 📝 File Information

- **File:** `src/webots/worlds/house.wbt`
- **Format:** VRML R2023b
- **Lines:** 584
- **Objects:** 17 (1 robot + 16 furniture/objects)
- **Physics:** Enabled
- **Status:** Ready for simulation

## 🚀 Starting the Simulation

1. **Load world:**
   ```bash
   ./scripts/run_webots.sh
   ```
   Then open `src/webots/worlds/house.wbt` in Webots

2. **Run agent:**
   ```bash
   uv run python -m src.ui.server
   ```

3. **Search for objects:**
   - Goal: "find cup"
   - Policy: "smart vision (VLM)"
   - Click: RUN

## 🎮 Testing Scenarios

### Scenario 1: Find Cup
- **Goal:** "find cup"
- **Expected:** Robot searches and locates cup on dining table
- **Success Criteria:** Agent reports finding cup within 20 steps

### Scenario 2: Explore Kitchen
- **Goal:** "explore kitchen area"
- **Expected:** Robot navigates to north side, finds counter and fridge
- **Success Criteria:** Agent explores kitchen objects

### Scenario 3: Multi-object Search
- **Goal:** "find cup and football"
- **Expected:** Robot searches for both objects
- **Success Criteria:** Agent locates both items

### Scenario 4: Area Mapping
- **Goal:** "explore the area"
- **Expected:** Robot maps out entire space
- **Success Criteria:** Agent explores all rooms systematically

## 📊 Object Detection

Objects designed for easy detection by YOLO:
- ✅ **Cup** - Yellow color, clear shape
- ✅ **Football** - Brown, distinctive elongated form
- ✅ **Plant** - Green cylinder, natural color
- ✅ **Furniture** - Large blocks, varied colors
- ✅ **Fridge** - Gray metallic appearance
- ✅ **Dish** - White, flat, on counter

All objects have good contrast with environment for visual detection.

## 🔍 Camera View

**Robot Camera Specifications:**
- **Resolution:** 320×240 pixels
- **Field of View:** 0.8 radians (≈45.8 degrees)
- **Near Plane:** 0.01m
- **Far Plane:** 50m
- **Position:** 0.9m above robot base center

**View Range from Robot:**
- **Minimum Distance:** 0.01m
- **Maximum Distance:** 50m
- **Horizontal FOV:** ~45.8 degrees
- **Vertical FOV:** ~34.2 degrees

## ⚠️ Common Issues

### Robot Stuck in Corner
- **Solution:** Restart simulation, robot starts at (1, 0.62, 1)
- **Tip:** Try different movement commands

### Can't Find Objects
- **Check:** Is object in robot's field of view?
- **Try:** Increase max steps (e.g., 50 instead of 20)
- **Verify:** Object is placed above ground (Y > 0.3)

### Simulation Too Slow
- **Solution:** Reduce simulation speed in Webots menu
- **Or:** Increase simulation time step (edit `basicTimeStep`)

### Objects Not Visible in Camera
- **Cause:** Objects outside FOV or behind walls
- **Fix:** Robot needs to move to explore all areas

## 📈 Expansion Ideas

- **Add More Objects:** Chairs, tables, lamps, decorations
- **Add Obstacles:** Walls between rooms, pillars
- **Add Lighting:** Dynamic lights, shadows
- **Add Sensors:** Temperature, humidity for rooms
- **Add Tasks:** Multi-room navigation, object collection
- **Add Animation:** Moving objects, sliding doors

## ✅ Verification Checklist

- ✓ World loads without errors
- ✓ Robot spawns at correct position
- ✓ Camera captures images properly
- ✓ All 17 objects are visible
- ✓ Physics simulation stable
- ✓ Objects have correct colors for detection
- ✓ Lighting is appropriate for vision tasks
- ✓ Arena walls contain all objects

---

**Ready to explore!** Start Webots with this world and use the smart vision agent to search for objects. 🏠🤖
