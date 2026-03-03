#!/bin/bash
# CUE Enhancer — Benchmark Environment Setup
# Target: Ubuntu 22.04 VPS with Xvfb
# Usage: bash scripts/setup_benchmark_env.sh

set -euo pipefail

echo "=== CUE Benchmark Environment Setup ==="
echo "Installing applications for mini_benchmark suite..."

# Update package lists
sudo apt-get update

# LibreOffice (Calc + Writer)
echo "[1/6] Installing LibreOffice..."
sudo apt-get install -y libreoffice-calc libreoffice-writer libreoffice-common

# Firefox
echo "[2/6] Installing Firefox..."
sudo apt-get install -y firefox

# Chromium
echo "[3/6] Installing Chromium..."
sudo apt-get install -y chromium-browser || sudo snap install chromium

# GIMP
echo "[4/6] Installing GIMP..."
sudo apt-get install -y gimp

# File Manager (Nautilus / PCManFM for lightweight)
echo "[5/6] Installing File Manager..."
sudo apt-get install -y pcmanfm || sudo apt-get install -y nautilus

# VS Code (via snap or deb)
echo "[6/6] Installing VS Code..."
if ! command -v code &> /dev/null; then
    # Install via official Microsoft repo
    wget -qO- https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > /tmp/packages.microsoft.gpg
    sudo install -D -o root -g root -m 644 /tmp/packages.microsoft.gpg /etc/apt/keyrings/packages.microsoft.gpg
    echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/packages.microsoft.gpg] https://packages.microsoft.com/repos/code stable main" \
        | sudo tee /etc/apt/sources.list.d/vscode.list
    sudo apt-get update
    sudo apt-get install -y code
fi

# Additional tools for env_extractor
echo "[+] Installing extraction tools..."
sudo apt-get install -y wmctrl xclip xsel xterm

# Verify installations
echo ""
echo "=== Verification ==="
for cmd in libreoffice firefox chromium-browser gimp pcmanfm code xterm wmctrl xclip; do
    if command -v "$cmd" &> /dev/null; then
        echo "  OK $cmd"
    else
        echo "  MISSING $cmd (not found)"
    fi
done

echo ""
echo "=== Setup Complete ==="
echo "To run benchmark: python -m cue.benchmark.cli --suite mini_benchmark --dry-run"
