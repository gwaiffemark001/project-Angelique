#!/bin/bash

echo " Setting up Angelique GUI and Advanced Features..."

# Create directory structure
echo "📁 Creating directories..."
mkdir -p gui
mkdir -p skills/voice
mkdir -p skills/messaging
mkdir -p skills/file_management
mkdir -p skills/self_evolution
mkdir -p skills/trading/engine
mkdir -p skills/trading/market
mkdir -p data/generated_images
mkdir -p data/generated_skills

# Create empty __init__.py files
echo "📄 Creating __init__.py files..."
touch gui/__init__.py
touch skills/voice/__init__.py
touch skills/messaging/__init__.py
touch skills/file_management/__init__.py
touch skills/self_evolution/__init__.py
touch skills/trading/engine/__init__.py
touch skills/trading/market/__init__.py

# Create launcher.py
echo "📝 Creating launcher.py..."
cat > launcher.py << 'EOF'
import sys
import os
import subprocess

def launch_gui(floating=False):
    """Launch Angelique with GUI"""
    cmd = [sys.executable, "gui/angelique_gui.py"]
    if floating:
        cmd.append("--floating")
    subprocess.run(cmd)

def launch_terminal():
    """Launch Angelique in terminal mode"""
    from main import main as terminal_main
    terminal_main()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "--gui":
            launch_gui()
        elif sys.argv[1] == "--floating":
            launch_gui(floating=True)
        else:
            launch_terminal()
    else:
        print(" Launching Angelique GUI...")
        print("Use --floating for floating mode")
        print("Use --terminal for terminal mode")
        launch_gui()
EOF

# Create start_angelique.sh
echo "📝 Creating start_angelique.sh..."
cat > start_angelique.sh << 'EOF'
#!/bin/bash

PROJECT_DIR="$HOME/Desktop/Projects/project-Angelique"
LOG_DIR="$PROJECT_DIR/data/logs"
mkdir -p "$LOG_DIR"

echo "🚀 [Bootstrap] Starting Angelique Environment..."

# Activate Virtual Environment
if [ -f "$PROJECT_DIR/.venv/bin/activate" ]; then
    source "$PROJECT_DIR/.venv/bin/activate"
else
    echo "❌ [Bootstrap] Virtual environment not found"
    exit 1
fi

# Launch MT5 Bridge Server in Wine (if not already running)
BRIDGE_SCRIPT="$PROJECT_DIR/skills/trading/engine/mt5_bridge_server.py"
if ! pgrep -f "mt5_bridge_server.py" > /dev/null; then
    echo "🍷 [Bootstrap] Launching MT5 Bridge Server inside Wine..."
    wine python "$BRIDGE_SCRIPT" > "$LOG_DIR/mt5_bridge.log" 2>&1 &
else
    echo "✅ [Bootstrap] MT5 Bridge Server is already running."
fi

# Wait for the Bridge to be ready
echo " [Bootstrap] Waiting for MT5 Bridge to initialize on port 9999..."
timeout=30
while [ $timeout -gt 0 ]; do
    if (echo > /dev/tcp/localhost/9999) 2>/dev/null; then
        echo "✅ [Bootstrap] MT5 Bridge is ready and listening!"
        break
    fi
    sleep 1
    timeout=$((timeout - 1))
done

if [ $timeout -eq 0 ]; then
    echo "⚠️ [Bootstrap] MT5 Bridge did not start in time."
fi

# Launch Angelique
echo "🟢 [Bootstrap] Launching Angelique v2..."
cd "$PROJECT_DIR"
python3 main.py
EOF

chmod +x start_angelique.sh

echo "✅ Basic setup complete!"
echo ""
echo "Now run the following commands to create the GUI files:"
echo "  python3 create_gui_files.py"
echo ""
echo "Then install dependencies:"
echo "  pip install customtkinter matplotlib pillow"

