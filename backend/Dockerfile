# Imagen del backend (API y workers). Se usa con `docker compose --profile app up -d worker-fiscal`.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app/backend
ENV UV_PROJECT_ENVIRONMENT=/opt/venv PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 TZ=America/Bogota
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
