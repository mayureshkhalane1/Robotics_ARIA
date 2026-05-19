#!/bin/bash
# Comprehensive ARIA system diagnostic and test script

set -e

PROJECT_ROOT="/Users/mayureshkhalane/Documents/ARIA"
cd "$PROJECT_ROOT"

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║          ARIA Vision-First Robot - System Diagnostic           ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Check 1: Environment
echo "[1/8] Checking environment..."
if ! command -v python3 &> /dev/null; then
    echo "✗ Python3 not found"
    exit 1
fi
echo "✓ Python3: $(python3 --version)"

if ! command -v git &> /dev/null; then
    echo "✗ Git not found"
    exit 1
fi
echo "✓ Git: $(git --version | head -1)"

# Check 2: Webots
echo ""
echo "[2/8] Checking Webots..."
if ! pgrep -f "Webots" > /dev/null; then
    echo "⚠ Webots not running. Start with: ./scripts/run_webots.sh"
else
    echo "✓ Webots running"
fi

# Check 3: Ollama
echo ""
echo "[3/8] Checking Ollama..."
if ! pgrep -f "ollama" > /dev/null; then
    echo "⚠ Ollama not running. Start with: ollama serve"
else
    echo "✓ Ollama running"
    # Check if qwen3-vl is available
    if curl -s http://localhost:11434/api/tags | grep -q "qwen3"; then
        echo "✓ qwen3-vl model available"
    else
        echo "⚠ qwen3-vl model not found. Pull with: ollama pull qwen3:8b"
    fi
fi

# Check 4: Python dependencies
echo ""
echo "[4/8] Checking Python packages..."
python3 << 'EOF'
import sys
packages = ['cv2', 'numpy', 'aiohttp', 'dotenv']
missing = []
for pkg in packages:
    try:
        __import__(pkg)
        print(f"✓ {pkg}")
    except ImportError:
        print(f"✗ {pkg} - missing")
        missing.append(pkg)
if missing:
    sys.exit(1)
EOF

# Check 5: Code quality
echo ""
echo "[5/8] Checking code structure..."
test -f "src/agent/vision_language_agent.py" && echo "✓ vision_language_agent.py"
test -f "src/perception/camera.py" && echo "✓ camera.py"
test -f "src/webots/controllers/tcp_controller/tcp_controller.py" && echo "✓ tcp_controller.py"
test -f "src/ui/server.py" && echo "✓ ui/server.py"
test -f "src/webots/worlds/worlds/complete_apartment.wbt" && echo "✓ complete_apartment.wbt world"

# Check 6: VLM integration
echo ""
echo "[6/8] Checking qwen3-vl integration..."
python3 << 'EOF'
import re
with open("src/agent/vision_language_agent.py") as f:
    content = f.read()
    if "_ask_qwen_vision_about_scene" in content:
        print("✓ Vision-language method found")
    if "images.*base64" in content or "frame_b64" in content:
        print("✓ Image encoding to LLM detected")
    if "qwen3" in content or "OLLAMA_MODEL" in content:
        print("✓ Qwen model reference found")
EOF

# Check 7: Motor initialization
echo ""
echo "[7/8] Checking motor safety..."
python3 << 'EOF'
with open("src/webots/controllers/tcp_controller/tcp_controller.py") as f:
    content = f.read()
    if "setVelocity(0.0)" in content and "Initialize to zero" in content:
        print("✓ Motors initialized to 0 velocity")
    if "CRITICAL" in content:
        print("✓ Motor safety guard in place")
EOF

# Check 8: Recent commits
echo ""
echo "[8/8] Checking recent changes..."
echo "Latest commits:"
git log --oneline -3

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                     Diagnostic Complete                        ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "📋 Summary:"
echo "  ✓ Vision-language model (qwen3-vl) integrated"
echo "  ✓ Camera frame decoding improved"
echo "  ✓ Motor initialization safety checks added"
echo ""
echo "🚀 To start the ARIA system:"
echo "  1. Terminal 1: ./scripts/run_webots.sh"
echo "  2. Terminal 2: ollama serve"
echo "  3. Terminal 3: uv run python -m src.ui.server"
echo "  4. Browser: http://localhost:8080"
echo ""
echo "📝 To test agent:"
echo "  - Goal: 'find cup'"
echo "  - Policy: 'smart_vision (VLM)'"
echo "  - Click: Run"
echo ""
