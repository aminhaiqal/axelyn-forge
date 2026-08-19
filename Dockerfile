FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fonts-crosextra-caladea \
        fonts-crosextra-carlito \
        fonts-liberation \
        libreoffice-writer \
    && rm -rf /var/lib/apt/lists/*

COPY deploy/fontconfig/99-axelyn-forge-font-substitutions.conf /etc/fonts/conf.d/
RUN fc-cache -f

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
