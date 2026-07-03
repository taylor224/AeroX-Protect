FROM python:3.13-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/usr/src/app \
    TZ=UTC

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/app

COPY worker/encoder/requirements.txt ./worker/encoder/requirements.txt
RUN pip install -r worker/encoder/requirements.txt

# Keep the worker.encoder package layout (absolute imports + dev-venv test parity).
COPY worker/ ./worker/

RUN groupadd -g 1000 app && useradd -u 1000 -g app -m -s /sbin/nologin app \
    && chown -R app:app /usr/src/app
USER app

EXPOSE 8098

CMD ["uvicorn", "worker.encoder.app:app", "--host", "0.0.0.0", "--port", "8098"]
