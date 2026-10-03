FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Dependencies first (cached until pyproject.toml / uv.lock change).
# --locked fails the build if uv.lock is out of date, instead of silently resolving.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# Then the package itself.
COPY src ./src
RUN uv sync --locked --no-dev

EXPOSE 8000

CMD ["uv", "run", "--no-sync", "uvicorn", "moviestream.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
