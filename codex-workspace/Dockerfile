FROM node:22-bookworm

ARG CODEX_VERSION=latest

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
       ripgrep \
       unzip \
       vim \
    && corepack enable \
    && npm install -g "@openai/codex@${CODEX_VERSION}" \
    && npm cache clean --force \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /workspace /home/node \
    && chown -R node:node /workspace /home/node

USER node
WORKDIR /workspace
ENV HOME=/home/node
ENV PATH=/home/node/.local/bin:${PATH}

CMD ["bash", "-lc", "sleep infinity"]
