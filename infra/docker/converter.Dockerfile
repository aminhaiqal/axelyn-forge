FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/tmp/forge-home

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fonts-crosextra-caladea \
        fonts-crosextra-carlito \
        fonts-liberation \
        libreoffice-writer \
    && rm -rf /var/lib/apt/lists/*

COPY infra/docker/fontconfig/99-axelyn-forge-font-substitutions.conf /etc/fonts/conf.d/
RUN fc-cache -f

COPY packages/forge-core ./packages/forge-core
COPY apps/converter ./apps/converter
RUN python -m pip install ./packages/forge-core ./apps/converter \
    && useradd --no-create-home --uid 10002 converter

USER converter

EXPOSE 8100

CMD ["forge-converter"]
