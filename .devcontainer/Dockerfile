FROM mcr.microsoft.com/devcontainers/python:3.12-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      default-mysql-client \
      postgresql-client \
      unzip \
    && rm -rf /var/lib/apt/lists/*

RUN pipx install poetry

COPY .devcontainer/scripts/setup-oracle-client.sh /usr/local/bin/setup-oracle-client
RUN chmod +x /usr/local/bin/setup-oracle-client
