FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY packages/forge-core ./packages/forge-core
COPY apps/api ./apps/api
RUN python -m pip install ./packages/forge-core ./apps/api

RUN useradd --create-home --uid 10001 forge \
    && mkdir -p /state/objects \
    && chown -R forge:forge /state

USER forge

VOLUME ["/state"]

EXPOSE 8000

CMD ["forge-api"]
