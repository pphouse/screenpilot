FROM python:3.12-slim

# Install system dependencies for screen capture and input control
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    x11-utils \
    xdotool \
    scrot \
    libx11-dev \
    libxext-dev \
    libxss-dev \
    libxkbcommon-x11-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY screenpilot/ screenpilot/

RUN pip install --no-cache-dir -e .

# Set up virtual display
ENV DISPLAY=:99
ENV SCREEN_WIDTH=1920
ENV SCREEN_HEIGHT=1080

# Start script that launches Xvfb and the API server
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 8420

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["screenpilot", "serve", "--port", "8420"]
