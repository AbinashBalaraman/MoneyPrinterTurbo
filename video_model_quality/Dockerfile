# Stickman Studio — container image for Render / Fly / Railway / any Docker host.
#
# Why a container and not serverless: the renderer shells out to ffmpeg to encode
# the MP4 and mux the soundtrack. Serverless platforms (Netlify/Vercel functions)
# provide no ffmpeg and cap execution at ~10s; a single clip takes 12-30s of CPU.
# So the engine needs a real, long-running machine.
FROM python:3.11-slim

# ffmpeg is the only system dependency: it encodes video and muxes the audio.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Only the runtime deps. pytest is a dev tool and is deliberately not installed.
RUN pip install --no-cache-dir "numpy>=1.24.0" "Pillow>=9.5.0"

COPY src/     ./src/
COPY tools/   ./tools/
COPY studio/  ./studio/

# Small-host defaults. Override any of these in the platform's env settings.
#   STUDIO_DEFAULT_SD=1     -> render 512x512 (4x cheaper than HD)
#   STUDIO_MAX_FRAMES=240   -> refuse clips longer than 10s so we never OOM
#   STUDIO_OUT_DIR=/tmp/... -> ephemeral scratch; clips live until restart
ENV STUDIO_DEFAULT_SD=1 \
    STUDIO_MAX_FRAMES=240 \
    STUDIO_OUT_DIR=/tmp/studio

EXPOSE 8770

# The server reads $PORT (injected by the platform) and binds 0.0.0.0 when it is
# set, so this same entrypoint works on a laptop and in a container.
CMD ["python", "tools/studio_server.py"]
