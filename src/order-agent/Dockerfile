# Use slim (Debian/glibc) not alpine (musl). github-copilot-sdk, pulled
# transitively by agent-framework, only ships manylinux/glibc wheels and
# will fail to install on musl-based images.
FROM python:3.14-slim

WORKDIR /app

ARG APP_VERSION=0.1.0

RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
RUN uv sync --no-dev

COPY . .

EXPOSE 7003
ENV APP_VERSION=$APP_VERSION

CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7003"]
