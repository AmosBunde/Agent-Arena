# Shared image for the api, runner, and scheduler services. One image, three
# commands (uvicorn, celery worker, celery beat); see
# deploy/compose/docker-compose.yml and ADR-0001.

FROM python:3.12-slim

WORKDIR /app

# Locked dependencies first so source edits do not bust the layer cache.
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

COPY pyproject.toml README.md LICENSE alembic.ini ./
COPY packages packages
COPY apps/api apps/api
COPY apps/runner apps/runner
COPY migrations migrations
RUN pip install --no-cache-dir -e . --no-deps

COPY deploy/docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Non-root user; the app writes nothing to the filesystem.
RUN useradd --create-home arena
USER arena

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
