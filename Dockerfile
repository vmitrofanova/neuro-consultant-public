FROM python:3.12-slim
WORKDIR /app

RUN pip install --no-cache-dir uv==0.8.23
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

COPY app/ app/
ENV PATH="/app/.venv/bin:${PATH}"
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
