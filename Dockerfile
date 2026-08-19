FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY forge ./forge
RUN python -m pip install .

COPY bindings ./bindings
COPY context ./context
COPY data/profile.json ./data/profile.json
COPY schemas ./schemas
COPY templates ./templates

RUN useradd --create-home --uid 10001 forge \
    && mkdir -p /state/output \
    && chown -R forge:forge /state

USER forge

VOLUME ["/state"]

CMD ["forge-discord"]
