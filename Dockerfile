FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Stub the app source so setuptools can resolve the dependency list without
# copying real Python files into the builder. The wheel we produce here is
# discarded; only the third-party dependency wheels go to the runtime stage.
COPY pyproject.toml README.md ./
RUN mkdir -p apps loom && \
    touch apps/__init__.py && \
    echo '__version__ = "0.0.0"' > loom/__init__.py
RUN python -m pip wheel --wheel-dir /wheels .


FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYSTOW_HOME=/tmp/pystow \
    APP_DIR=/opt/loom \
    PYTHONPATH=/opt/loom \
    GUNICORN_CMD_ARGS=--timeout=300

WORKDIR /opt/loom

COPY --from=builder /wheels /wheels
# Install third-party deps; uninstall the stub loom wheel. Real source goes to /opt/loom.
RUN apt-get update && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install /wheels/*.whl \
    && python -m pip uninstall -y loom \
    && rm -rf /wheels \
    && addgroup --system loom \
    && adduser --system --ingroup loom --home /home/loom loom \
    && mkdir -p /home/loom \
    && chown loom:loom /home/loom

# marker-pdf for LLM-assisted PDF-to-Markdown extraction.
# DISABLED: Marker now runs off-process via helper-scripts/marker_convert.py.
# TO RE-ENABLE: un-comment the RUN step below and follow the instructions in
# loom/settings/base.py and apps/documents/services.py.
#
# RUN python -m pip uninstall -y marker 2>/dev/null || true \
#     && python -m pip install "marker-pdf>=1.0,<2.0"

COPY docker/entrypoint.sh /usr/local/bin/loom-entrypoint
COPY manage.py ./
COPY apps ./apps
COPY loom ./loom
COPY config ./config
COPY docs ./docs
COPY static ./static
COPY templates ./templates

RUN chmod +x /usr/local/bin/loom-entrypoint \
    && mkdir -p /opt/loom/media /opt/loom/staticfiles \
    && SECRET_KEY=collectstatic-only ALLOWED_HOSTS=localhost \
       DJANGO_SETTINGS_MODULE=loom.settings.prod \
       python manage.py collectstatic --noinput \
    && chown -R loom:loom /opt/loom/media /opt/loom/staticfiles

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready/', timeout=3)" || exit 1
ENTRYPOINT ["loom-entrypoint"]
CMD ["gunicorn", "loom.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--access-logfile", "-"]
