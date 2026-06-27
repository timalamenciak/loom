FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY apps ./apps
COPY loom ./loom
RUN python -m pip wheel --wheel-dir /wheels .


FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY --from=builder /wheels /wheels
RUN python -m pip install /wheels/*.whl \
    && rm -rf /wheels \
    && addgroup --system loom \
    && adduser --system --ingroup loom --home /app loom

COPY manage.py ./
COPY config ./config
COPY docs ./docs
COPY static ./static
COPY templates ./templates

RUN mkdir -p /app/media /app/staticfiles \
    && SECRET_KEY=collectstatic-only DJANGO_SETTINGS_MODULE=loom.settings.prod \
       python manage.py collectstatic --noinput \
    && chown -R loom:loom /app/media /app/staticfiles

USER loom

EXPOSE 8000
CMD ["gunicorn", "loom.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--access-logfile", "-"]
