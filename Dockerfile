# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e

# Supply an immutable python:3.13-slim image reference ending in @sha256:<digest>.
ARG PYTHON_BASE_IMAGE
FROM ${PYTHON_BASE_IMAGE} AS runtime

ARG POETRY_VERSION=2.2.1

ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN python -m pip install "poetry==${POETRY_VERSION}"

COPY pyproject.toml poetry.lock README.md ./
RUN poetry install --only main --no-root --no-ansi

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY tools ./tools

RUN addgroup --system --gid 10001 recording-agent \
    && adduser --system --uid 10001 --ingroup recording-agent --home /nonexistent \
        --no-create-home recording-agent \
    && chown -R recording-agent:recording-agent /app

USER 10001:10001

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
