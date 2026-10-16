# Ask OLake: the API, the widget files and the prebuilt index in one image (plan §4.5 D1, D3).
#
#   docker build -t ask-olake:local --build-arg GIT_SHA=$(git rev-parse --short HEAD) .
#   docker run --rm -p 8080:8080 --env-file .env ask-olake:local
#
# The index is built on the laptop (uv run python -m index.build) and copied in: the corpus is never embedded
# during the build or at container start. The query-side models are downloaded at build time.

ARG PYTHON_IMAGE=python:3.12-slim

# ----------------------------------------------------------------------------- build: dependencies and models
FROM ${PYTHON_IMAGE} AS build
RUN pip install --no-cache-dir uv==0.11.7
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/app/.venv \
    FASTEMBED_CACHE_PATH=/app/models TIKTOKEN_CACHE_DIR=/app/models/tiktoken HF_HOME=/app/models/hf
COPY pyproject.toml uv.lock .python-version README.md ./
# dependencies only: the code runs from /app (WORKDIR on sys.path), so its paths stay inside /app
RUN uv sync --frozen --no-dev --extra rerank --no-install-project
# the query embedder, the optional TinyBERT reranker (RERANK=tinybert) and the o200k tokenizer
RUN /app/.venv/bin/python -c "\
from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/app/models'); \
from flashrank import Ranker; Ranker(model_name='ms-marco-TinyBERT-L-2-v2', cache_dir='/app/models/flashrank'); \
import tiktoken; tiktoken.get_encoding('o200k_base'); print('models ready')" \
 && rm -rf /app/models/flashrank/__MACOSX /app/models/hf/xet
# the index: only the version CURRENT names (older versions in the tree never reach a layer)
COPY data/index/ /app/data/index/
RUN cur=$(tr -d '[:space:]' < /app/data/index/CURRENT) && test -f "/app/data/index/$cur/manifest.json" \
 && find /app/data/index -mindepth 1 -maxdepth 1 -type d ! -name "$cur" -exec rm -rf {} + \
 && echo "index $cur" && ls /app/data/index

# ----------------------------------------------------------------------------- runtime
FROM ${PYTHON_IMAGE}
ARG GIT_SHA=unknown
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH=/app/.venv/bin:$PATH \
    FASTEMBED_CACHE_PATH=/app/models TIKTOKEN_CACHE_DIR=/app/models/tiktoken HF_HOME=/app/models/hf \
    HF_HUB_OFFLINE=1 GIT_SHA=${GIT_SHA} PORT=8080
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY --from=build --chown=app:app /app/models /app/models
COPY pyproject.toml ./
COPY app/ app/
COPY ingest/ ingest/
COPY index/ index/
COPY web/ web/
COPY --from=build --chown=app:app /app/data/index/ data/index/
# .cache holds the refresher's poll state and lock; data/index takes new versions when the in-app refresher runs
RUN mkdir -p /app/.cache && chown app:app /app/.cache /app/data
USER app
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
