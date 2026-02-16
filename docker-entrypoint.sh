#!/bin/bash
set -e

# Start virtual framebuffer
Xvfb :99 -screen 0 ${SCREEN_WIDTH}x${SCREEN_HEIGHT}x24 &
sleep 1

# Execute the command
exec "$@"
