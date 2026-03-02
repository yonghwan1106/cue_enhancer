#!/usr/bin/env bash
set -euo pipefail

# Start Xvfb (virtual display)
Xvfb :99 -screen 0 1920x1080x24 -ac &
XVFB_PID=$!
sleep 0.5

# Start AT-SPI2 registry daemon (accessibility)
/usr/libexec/at-spi2-registryd &
sleep 0.2

# Start xterm (default terminal for CUE to interact with)
xterm -geometry 120x40+0+0 &
sleep 0.3

# If arguments provided, run CUE with them; otherwise enter interactive mode
if [ $# -eq 0 ] || [ "$1" = "--help" ]; then
    echo "CUE Enhancer Docker Container"
    echo ""
    echo "Usage:"
    echo "  docker run -e ANTHROPIC_API_KEY=... cue-enhancer cue run \"task description\""
    echo "  docker run -e ANTHROPIC_API_KEY=... cue-enhancer python3 -m pytest tests/ -q"
    echo "  docker run -it -e ANTHROPIC_API_KEY=... cue-enhancer bash"
    echo ""
    exec bash
else
    exec "$@"
fi
