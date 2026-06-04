# ARIA — Status, Issues, and Analysis

_Last updated: 2026-06-04, after analysing `run_20260604_155607.log` (break_room) and
`run_20260604_160223.log` (empty_room)._

This document exists so we have one honest, plain-language record of **what ARIA is
trying to do, what is actually happening, what has been fixed, and what is still
uncertain** — independent of any single chat session.

---

## 1. What ARIA is supposed to do

A Pioneer 3-DX robot in Webots R2025a that, given a goal like `find the dog` or
`find the dog and approach it`:

1. **Explores the room using only its own sensors** (Lidar + camera). It is *not*
   given the floor plan and must not depend on wall colour or on coordinates read
   from the `.wbt`.
2. **Recognises the target with YOLO** (the camera detector), every step.
3. **Acts on the goal:**
   - `find X` → stop and look at X the moment it is seen.
   - `find X and approach it` → drive up to X (visual servoing) and stop when close.
4. When the whole reachable area is explored and X was never seen → report "not found".

The Python agent runs in WSL2; Webots (and optional Ollama) run on Windows. They talk
over TCP (port 19997). The LLM is an **optional** layer — navigation and detection work
without it.

---

## 2. Architecture (brief)

```
aria_agent.py   main loop: SENSE → DECIDE → ACT, one closed-loop motion per step
  online_map.py     live Lidar occupancy grid (free/occupied/unknown) + frontier + BFS
  grid_explorer.py  heading→turn helper + 360° scan state machine
  spatial_memory.py records YOLO detections to logs/spatial_memory.json
object_detector.py  YOLOv8 (COCO classes) / YOLO-World (open vocabulary)
tcp_controller.py   Webots side: closed-loop turn (compass) / move (GPS), reads Lidar
```

**Decision priority each step (current, after the fix below):**
1. **Target pursuit** — YOLO sees the target now → approach (servo) or stop (find).
2. **Re-acquire** — just lost it → turn back toward last-seen side for a few steps.
3. **Mid-scan** — continue the 360° look-around in 45° steps.
4. **Explore** — no current frontier → 360° scan, pick nearest reachable frontier.
5. **Drive frontier** — head toward the chosen frontier; on arrival re-scan; if no
   progress for several steps, blacklist it and re-scan.
6. **Explored everything, target not seen** → stop, "not found".

---

## 3. The bug these two runs exposed (root cause)

**Symptom:** in *both* worlds the robot rotates endlessly, "finds things but gets
confused", and never explores. In the empty room — which has no obstacles at all — it
still just spins.

**Evidence (every step of both logs):**
```
[ARIA] Known target → turn_right_45  navigating to known dog (-0.6,4.2) dist=0.5m
```
In `run_20260604_160223.log` the position is **frozen at `(-0.21, 3.84)` from step 9 to
the end**, while the heading cycles 42° → −4° → −49° → … (turning right 45° every step).
It never moves and never stops.

**Root cause — spatial-memory recall hijacked the whole agent:**

The agent had a branch that said *"if the target was seen in a previous run, drive
straight to that stored coordinate instead of exploring."* Because
`logs/spatial_memory.json` already contained a `dog` at `(-0.6, 4.2)` from earlier
break_room runs, this branch fired on **step 1 of every run** and starved the
exploration/scan code that was supposed to do the work. Three compounding failures:

1. **It overrode the autonomous design.** The robot you built to explore from sensors
   was instead blindly driving to a stored point — the exact thing the project is meant
   *not* to do.
2. **Wrong world.** Spatial memory is keyed by the *configured* world file
   (`WEBOTS_WORLD_FILE`, still `break_room.wbt`), but the agent only talks to Webots over
   TCP and **cannot know which world you actually loaded**. So in `empty_room.wbt` it
   loaded *break_room's* dog and drove toward a dog that does not exist there. No dog →
   YOLO pursuit never triggers → stuck forever.
3. **No convergence / no give-up.** Near the phantom coordinate the goal cell is
   unknown/blocked in the live map, the path planner returns nothing usable, and the
   recall branch had no "I'm here and see nothing, give up" path — so it span in place.

This also explains the *first* run (break_room): it crammed itself into the entrance
corner trying to reach the phantom dog coordinate and triggered repeated critical-
proximity back-ups (`proximity 970–1040`).

---

## 4. The fix applied (this session)

**Removed the blind "drive to a remembered coordinate" branch** from the decision loop
in `aria_agent.py`. Spatial memory is still **recorded** (for analysis and the UI) but
it **no longer drives navigation**. Consequences:

- Every run now always runs the autonomous loop: **360° scan → nearest frontier →
  drive → re-scan**, with YOLO every step.
- The moment YOLO actually sees the target, **pursuit** takes over (approach or stop).
- When the whole reachable area is explored and the target was never seen, the robot
  stops and reports "not found" — the correct result for `find the dog` in a room with
  no dog (e.g. the empty room).

This is faithful to the stated design: explore with sensors, recognise with the camera,
then act. Memory recall can be re-introduced later as a *soft bias* (prefer frontiers
near a remembered spot) once the world-keying problem (below) is solved — but it must
never again replace live exploration.

`logs/spatial_memory.json` currently holds mostly mis-detections (umbrella, stop sign,
train, airplane, traffic light, …) from earlier runs. It is now harmless to navigation;
delete it any time for a clean slate (`rm logs/spatial_memory.json`).

---

## 5. What is fixed vs. still uncertain

**Fixed / confident:**
- The spin-in-place hijack is removed; the robot will now explore on every run.

**Verified in `run_20260604_164900.log` (empt_room, `find the dog and approach it`):**

- **World detection works** — `getWorldPath()` exists on this Webots build and returned
  `empt_room`; floor bounds used the correct file.
- **Frontier-drive convergence + translation work.** The robot scanned, picked frontiers
  `(-3.2,3.5) → (-3.1,4.0) → (-0.7,-2.1) → (5.7,3.8)`, **translated in clean ~0.6 m
  `move_forward` steps** (≈30 of them, `MOVED dist=0.60–0.61m`), traversed diagonally
  across the room from `(0.07,-1.67)` to `(5.65,3.58)`, **blacklisted 2 dead-end
  frontiers**, and correctly concluded **'dog' not found** in the empty room. The
  spin-in-place hijack is gone.
- **Defect found & fixed:** it printed `EXPLORATION COMPLETE` **23×** and ran to
  `Step 100/100` instead of stopping — the complete-branch set `stop` but never broke the
  loop. Added `exploration_done` → the run now ends the first time exploration is
  exhausted.

**Approach path — VALIDATED (`run_20260604_163054.log`):** the robot spawned facing the
dog, YOLO emitted `dog` at `bbox 59%`, and it did `TARGET[approach] → stop → SUCCESS` on
step 1. So the pursuit/approach/stop logic works *whenever YOLO actually reports the
target*.

**Real blocker — PERCEPTION (this is what made it "confused"):**

- In the `empt_room` runs YOLO never emitted `dog` — only false positives (sink, bed,
  umbrella, plant). Up close the dog model reads as **`horse`** below the `0.35`
  confidence threshold, so it was filtered out and never logged or pursued. `dog`'s alias
  set was only `{'dog'}`, so a `horse` reading couldn't match the target → no pursuit →
  it kept exploring and gave up.
- **Fix 1 (applied):** target aliases now include the COCO quadrupeds YOLO confuses on a
  single animal model (`dog/cat/horse/sheep/cow/bear/…`), so a `horse` reading triggers
  pursuit of the dog. Trade-off: in a single-animal world this is correct; a quadruped
  *false positive* on furniture could now trigger pursuit — the readable pursuit log line
  (x-err/bbox/conf) will reveal it if it happens.
- **Fix 2 (applied):** the log-timestamp wrapper had `f"…{line}\n"[:-4]` which chopped the
  **last 4 characters off every log line** (`conf=0.41` → `conf=0`, `turn_right_45` →
  `turn_right`). Fixed so logs are readable and show real confidences.
- **Recommended (user-tunable, not changed):** set `YOLO_CONF=0.25` in `.env` so the
  flickering sub-threshold quadruped detections cross the bar. With logs now readable,
  the next run's real `conf=` values let us pick the threshold from data.

**Still uncertain:** whether, with the alias + lower conf, the dog is detected *reliably
enough at range* to pursue across the room (vs only when already close, as in 163054).
- **Camera 180° rotation.** Approach turn direction assumes the camera image is rotated
  180°. If, on `…and approach it`, the robot turns *away* from a visible target, flip the
  single marked comparison in the pursuit block of `aria_agent.py`
  (`target_err > 0` ↔ `< 0`).
- **YOLO vocabulary.** Standard YOLO only knows the 80 **COCO** classes. `dog`, `cat`,
  `sports ball`, `chair`, `bottle`, `person` work; **`duck` and `wooden box` do not** —
  the model literally cannot name them (it mislabels them, e.g. "umbrella"/"airplane",
  visible in the logs). For arbitrary objects set `YOLO_MODEL=yolov8s-world.pt` in `.env`
  (open-vocabulary; the agent feeds it the target words).
- **World identity — RESOLVED.** The TCP controller now reports the loaded world
  (`get_state` → `"world"`), and the agent uses it to key spatial memory and to read the
  correct floor bounds (it resolves `<worlds_dir>/<world>.wbt`). If the controller can't
  detect the world on your Webots build, it prints a diagnostic dump of all `WEBOTS_*`
  env vars to the Webots console, and the agent logs `Webots reports world: None (sources: …)`
  — send me that and we'll lock onto the right source. Until detection works it falls back
  to `WEBOTS_WORLD_FILE` (no regression).

---

## 6. What the *robot* (not the code) struggles with

- **Sensing the target at distance.** YOLO on a low-res sim camera misses small/distant
  objects and produces phantom labels (stop sign, train, airplane) from clutter. This
  is why a confident, close detection is needed before pursuit engages.
- **Tight corners.** Near walls/clutter the sonar ring trips the critical-proximity
  back-up repeatedly; the robot needs open space to turn. Spawning it inside the room
  (not jammed in the entrance alcove) helps a lot.
- **Line-of-sight approach only.** Approach is camera-driven; if furniture sits *between*
  the robot and a target it can still see over, it may stall. Open-floor targets work.

---

## 7. How to verify the next run

1. In `.env`: `ARIA_USE_LLM=0` (fastest, removes Ollama from the picture).
2. (Optional clean slate) `rm logs/spatial_memory.json`.
3. Load the world you want in Webots, press ▶.
4. Run the agent, goal `find the dog` first (simplest: stop on sight).
5. **In the new `logs/run_*.log`, check the start + first ~12 steps:**
   - Near the top: `[ARIA] Webots reports world: '<name>' (sources: …)`. If it says
     `None`, the controller couldn't detect the world — check the Webots console for the
     dumped `WEBOTS_*` env vars and send them over.
   - You should see `Starting 360° look-around` and `Scan done → frontier (x,y)`.
   - Each motion now logs `[ARIA] MOVED dist=…m turned=…° reached=… steps=…`. After the
     scan, on `move_forward` steps the **`dist` should be non-zero** — that confirms the
     robot actually translates, not just rotates.
   - You should *not* see `navigating to known …` any more (that branch is gone).
6. Then try `find the dog and approach it` and watch whether it drives up to the dog.

If step 5 shows it scanning then `move_forward` with `dist≈0.000m` (commanded to move but
not translating), capture that log — the next fix target is the frontier-drive
bearing/path planner or the closed-loop move, not memory.

---

## 8. Open questions for you

- Do you want spatial memory back as a *soft* hint (explore toward a remembered area
  first), or keep it record-only? (World-keying is now correct, so this is safe to add.)
- Making the agent ask Webots which world is loaded is **done** (§5). If the controller
  still reports `world: None` on your build, send the dumped `WEBOTS_*` env vars and I'll
  add the right source.
