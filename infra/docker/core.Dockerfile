FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /work

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fonts-crosextra-caladea \
        fonts-crosextra-carlito \
        fonts-liberation \
        libreoffice-writer \
    && rm -rf /var/lib/apt/lists/*

COPY infra/docker/fontconfig/99-axelyn-forge-font-substitutions.conf /etc/fonts/conf.d/
RUN fc-cache -f

COPY packages/forge-core /opt/forge-core
RUN python -m pip install /opt/forge-core \
    && useradd --create-home --uid 10001 forge \
    && chown forge:forge /work

USER forge

ENTRYPOINT ["forge"]
CMD ["--help"]
