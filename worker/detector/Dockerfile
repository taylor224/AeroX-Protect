FROM python:3.13-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/usr/src/app \
    TZ=UTC

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/app

COPY worker/detector/requirements.txt ./worker/detector/requirements.txt
RUN pip install -r worker/detector/requirements.txt
# Real inference (optional, heavy): bake YOLO/torch/opencv into the image.
# COPY worker/detector/requirements-inference.txt ./worker/detector/requirements-inference.txt
# RUN pip install -r worker/detector/requirements-inference.txt

# Keep the worker.detector package layout (absolute imports + dev-venv test parity).
COPY worker/ ./worker/

RUN groupadd -g 1000 app && useradd -u 1000 -g app -m -s /sbin/nologin app \
    && chown -R app:app /usr/src/app
USER app

EXPOSE 8099

CMD ["uvicorn", "worker.detector.app:app", "--host", "0.0.0.0", "--port", "8099"]
