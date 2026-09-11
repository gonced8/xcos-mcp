# SPDX-License-Identifier: GPL-3.0-only
FROM python:3.12-slim-bookworm

ARG SCILAB_VERSION=2026.1.0
ARG SCILAB_ARCHIVE=scilab-2026.1.0.bin.x86_64-linux-gnu.tar.xz

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    XCOS_SERVER_MODE=streamable-http \
    XCOS_SERVER_HOST=0.0.0.0 \
    XCOS_SERVER_PORT=8000

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl default-jre libgl1 libxi6 libxt6 libxtst6 xauth xvfb xz-utils \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/scilab \
    && curl --fail --location --show-error --silent \
      "https://oos.eu-west-2.outscale.com/scilab-releases/${SCILAB_VERSION}/${SCILAB_ARCHIVE}" \
      --output /tmp/scilab.tar.xz \
    && tar -xJf /tmp/scilab.tar.xz -C /opt/scilab \
    && rm /tmp/scilab.tar.xz \
    && ln -s "/opt/scilab/scilab-${SCILAB_VERSION}/bin/scilab" /usr/local/bin/scilab \
    && ln -s "/opt/scilab/scilab-${SCILAB_VERSION}/bin/scilab-cli" /usr/local/bin/scilab-cli

RUN useradd --create-home --shell /usr/sbin/nologin xcos
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir . && chown -R xcos:xcos /app

USER xcos
EXPOSE 8000
CMD ["xcos-mcp"]
