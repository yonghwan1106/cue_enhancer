FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:99 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 python3.11-venv python3.11-dev python3-pip \
    xvfb xterm xdotool scrot xsel x11-utils \
    tesseract-ocr imagemagick \
    at-spi2-core gir1.2-atspi-2.0 libgirepository1.0-dev \
    gcc pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Make python3.11 the default
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1

WORKDIR /opt/cue_enhancer

# Copy source and install
COPY pyproject.toml .
COPY cue/ cue/
COPY tests/ tests/
RUN python3 -m pip install --no-cache-dir --upgrade pip \
    && python3 -m pip install --no-cache-dir -e ".[dev]"

# Entrypoint
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

VOLUME /root/.cue

ENTRYPOINT ["entrypoint.sh"]
CMD ["--help"]
