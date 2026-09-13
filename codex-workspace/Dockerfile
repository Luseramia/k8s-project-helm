FROM node:22-bookworm

# Build with the exact version verified in the existing Pod.
ARG CODEX_VERSION

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       bash \
       build-essential \
       ca-certificates \
       curl \
       git \
       jq \
       less \
       nano \
       openssh-client \
       procps \
       python3 \
       python3-pip \
       python3-venv \
       ripgrep \
       tini \
       unzip \
       vim \
    && corepack enable \
    && test -n "${CODEX_VERSION}" \
    && test "${CODEX_VERSION}" != "latest" \
    && npm install -g "@openai/codex@${CODEX_VERSION}" \
    && npm cache clean --force \
    && rm -rf /var/lib/apt/lists/*

COPY gateway/requirements.txt /opt/codex-gateway/requirements.txt
RUN python3 -m venv /opt/codex-gateway/venv \
    && /opt/codex-gateway/venv/bin/pip install --no-cache-dir -r /opt/codex-gateway/requirements.txt
COPY gateway /opt/codex-gateway/gateway
RUN mkdir -p /workspace /home/node /opt/codex-gateway/workspace \
    && chown -R node:node /workspace /home/node /opt/codex-gateway/workspace

USER node
WORKDIR /workspace
ENV HOME=/home/node
ENV PATH=/home/node/.local/bin:${PATH}
ENV PYTHONPATH=/opt/codex-gateway
ENV PYTHONDONTWRITEBYTECODE=1
LABEL org.opencontainers.image.version="${CODEX_VERSION}"
EXPOSE 8080

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/opt/codex-gateway/venv/bin/python", "-m", "uvicorn", "gateway.app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--timeout-graceful-shutdown", "15"]
