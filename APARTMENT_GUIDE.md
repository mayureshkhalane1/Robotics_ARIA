# Apartment World - Pioneer 3-DX Setup

## Overview

The apartment world is a lightweight, fully self-contained Webots scene built from **Webots built-in PROTOs** (via `webots://` URLs). It avoids external downloads, uses a Pioneer 3‑DX robot, and includes a few indoor props plus searchable objects for the ARIA agent.

**Key points:**
- Uses Webots **R2024a+** built-in assets (no external texture/proto downloads).
- Robot: **Pioneer3dx** with `tcp_controller`.
- Sensors: **GPS**, **Compass**, **Camera**.
- Simple apartment layout: floor, divider walls, furniture, and props.

## Robot Configuration

- **Robot:** `Pioneer3dx` (built-in PROTO)
- **Controller:** `tcp_controller`
- **Motors:** `left wheel motor`, `right wheel motor` (default Pioneer 3‑DX names)
- **Sensors:**
  - `gps`
  - `compass`
  - `camera` (320×240)

## Objects in the World

- **Cup** (`cup`) – yellow cylinder on the table
- **Football** (`football`) – small brown box on the floor
- **Bottle** (`bottle`) – blue cylinder on the cabinet
- **Furniture:** sofa, table, bed, cabinet (static solids)
- **Walls:** divider and kitchen wall (static solids)

## How to Run

1. Start Webots (R2024a+ recommended).
2. Open the world:
   ```text
   src/webots/worlds/apartment.wbt
   ```
3. Press **Play** ▶️ and confirm the Pioneer robot appears.

## Notes

- The world references **only built-in** PROTOs:
  - `TexturedBackground`
  - `TexturedBackgroundLight`
  - `RectangleArena`
  - `Pioneer3dx`
- If the scene is blank, verify Webots can resolve `webots://` URLs (standard in Webots installations).

## Verification Checklist

- [ ] World loads without missing PROTO warnings
- [ ] Pioneer 3‑DX robot is visible
- [ ] Cup, football, bottle are visible
- [ ] Pressing **Play** runs the simulation
- [ ] Controller logs show TCP server initialized
