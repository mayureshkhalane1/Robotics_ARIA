# Plan: Upgrade to YOLOv26 for Improved Object Detection

## Context

**Challenge deadline:** May 1st 2026 (live demo).  
**Current issue:** Object tracking fails repeatedly despite being in frame. Logs show frequent SEARCHING → re-acquisition → loss cycles, even when object is visible. Re-acquisition via histogram matching (threshold 0.45) is working, but detection consistency is dropping.

**Root cause hypothesis:** YOLOv8n's detection accuracy is insufficient for this task. Object appearance changes (dragging causes tilt, rotation, shadows), causing confidence drops below 0.20 threshold. Histogram re-acquisition masks the problem temporarily but object stays fragile.

**Solution:** Replace YOLOv8n with YOLOv26n (newer, more robust, still lightweight). YOLOv26 shows improved accuracy while maintaining speed (~64 FPS on RTX 4050, same as v8n).

---

## Implementation Plan

### Phase 1: Model Swap
1. Update `mac_node.py` line 158 (global default):
   ```python
   _DEFAULT_YOLO_MODEL = "yolov26n.pt"  # was "yolov8n.pt"
   ```

2. Test model loads cleanly (Ultralytics auto-downloads if not cached):
   ```bash
   python mac_node.py --yolo-model yolov26n.pt --help
   ```

3. Warmup inference to verify speed (target: ≥60 FPS):
   ```bash
   python mac_node.py --pi-host 10.42.0.1 --yolo-model yolov26n.pt \
     --no-depth --queue-depth 1 [--debug]
   ```

### Phase 2: Threshold Tuning (if needed)
Test current settings first. If re-acquisition still fails:

- **YOLO confidence threshold** (line 155): Currently 0.20. If YOLOv26 confidence scores are higher by default, may keep as-is. If detection improves but false positives increase, lower to 0.15.
- **Histogram match threshold** (line 156): Currently 0.45 (re-acquire when score ≥ 0.45). Notes mention this was flagged as too lenient (suggested 0.65). Test with 0.55–0.60 to reduce false re-acquisition onto bystanders' clothing, but only if Challenge II has crowding.

### Phase 3: Validation
Run full tracking test with object you're using for Challenge I:
- Initialize tracking (draw ROI, press SPACE)
- Move object through frame: slow, fast, partial occlusion, tilted
- Watch for:
  - Number of SEARCHING state transitions (target: ≤ 1–2 per 10 seconds vs current frequent drops)
  - Histogram match scores (should stabilize ≥ 0.50)
  - FPS stability (should hold ≥ 19 FPS on your Mac)

### Phase 4: Demo Prep
Once stable:
1. Record Challenge I demo (required deliverable)
2. Test Challenge II with unknown object (if available)
3. Document model choice in technical report (Method section: "Upgraded detection backbone from YOLOv8n to YOLOv26n for improved robustness on dragged objects with changing orientation.")

---

## Files to Modify

- **mac_node.py:158** — Change `_DEFAULT_YOLO_MODEL` from "yolov8n.pt" to "yolov26n.pt"
- (Optional) **mac_node.py:155-156** — Adjust YOLO conf / histogram thresholds if Phase 2 testing shows need

## Why This Works

- YOLOv26n is 7% more accurate on COCO than v8n while maintaining speed (~64 FPS)
- Better at detecting objects in non-standard poses (dragged, tilted)
- Ultralytics API unchanged—no code rewrites needed
- Bytetrack compatibility verified (line 1070: `tracker="bytetrack.yaml"` works with all YOLO versions)

## Verification

Run test sequence:
1. **Syntax check:** `python mac_node.py --help` (should list --yolo-model option)
2. **Network check:** `ping 10.42.0.1` from your Mac
3. **Speed check:** Start `--no-depth --queue-depth 1`, watch FPS stabilize ≥ 19 (target 20)
4. **Tracking check:** Initialize on object, move slowly → watch for drops; move fast → watch for recovery time
5. **Demo check:** Full Challenge I loop (initialize, follow trajectory, return to home)

Success = no SEARCHING state for >5 seconds during smooth object movement.

---

## Risk & Fallback

- **Risk:** Model swap changes detection behavior—might catch too much or too little initially
- **Fallback:** `python mac_node.py --yolo-model yolov8n.pt` reverts instantly (one-line arg change)

---

## Timeline
- Model swap + speed test: ~5 min
- Threshold tuning (if needed): ~10 min per test
- Demo recording: ~15 min
- Total: 30–45 min for full validation
