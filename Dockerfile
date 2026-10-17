FROM python:3.13-slim
RUN pip install --no-cache-dir uv==0.12.3
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY whygraph ./whygraph
COPY scenarios ./scenarios
RUN uv sync --frozen --no-dev
EXPOSE 8000
CMD ["uv", "run", "--no-dev", "uvicorn", "whygraph.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
