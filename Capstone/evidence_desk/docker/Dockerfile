FROM ghcr.io/astral-sh/uv:0.10.4 AS uvtool

FROM python:3.14-slim AS lock
COPY --from=uvtool /uv /usr/local/bin/uv
WORKDIR /work/docker
ENV UV_CACHE_DIR=/tmp/uv-cache
ENTRYPOINT ["uv"]

FROM python:3.14-slim AS app
COPY --from=uvtool /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock /opt/app/
RUN cd /opt/app && UV_CACHE_DIR=/tmp/uv-cache uv sync --frozen --no-install-project
ENV PATH="/opt/app/.venv/bin:${PATH}" \
    PYTHONPATH=/work/src \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp
WORKDIR /work
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
