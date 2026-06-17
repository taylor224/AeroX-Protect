FROM python:3.13-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=UTC

# Runtime deps: timezone, curl (healthcheck), ffmpeg (recorder/export/frame — P2).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata curl ffmpeg \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/app

COPY pyproject.toml ./
COPY config.py ./
COPY server ./server
COPY worker ./worker
COPY migrations ./migrations

# Build deps for C extensions (argon2-cffi, cryptography, uwsgi), purged after.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libffi-dev \
    && pip install poetry uwsgi \
    && poetry config virtualenvs.create false \
    && poetry lock \
    && poetry install --no-root \
    && apt-get purge -y --auto-remove build-essential libffi-dev \
    && rm -rf /root/.cache /var/lib/apt/lists/*

# P6 A1 — CLIP semantic search. CPU-only torch (≈200MB, not the ~2GB CUDA wheel) from the
# PyTorch CPU index, then open_clip (reuses the installed torch). server/service/semantic_embed.py
# lazy-loads this; absent → hash fallback. Kept OUT of poetry to avoid CUDA resolution.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchvision \
    && pip install --no-cache-dir open_clip_torch \
    && rm -rf /root/.cache

COPY server/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Non-root user
RUN groupadd -g 1000 app \
    && useradd -u 1000 -g app -m -d /home/app -s /sbin/nologin app \
    && chown -R app:app /usr/src/app
USER app

EXPOSE 10000

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uwsgi", \
     "--enable-threads", "--processes", "4", "--threads", "2", \
     "--chdir", "/usr/src/app", "--pythonpath", "/usr/src/app", \
     "--http-socket", ":10000", "--http-auto-chunked", "--http-raw-body", \
     "--harakiri", "0", "--disable-write-exception", "--module", "server:app"]
