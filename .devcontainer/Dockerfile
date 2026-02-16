# Optional Dockerfile (kept minimal, image in devcontainer.json already provides Python 3.13)
# This file can be used if you prefer a custom build instead of the prebuilt image.

FROM mcr.microsoft.com/devcontainers/python:1-3.13

# Install system dependencies often needed for building Python packages
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential gcc libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Ensure pipenv is available for installing from Pipfile
RUN pip install --no-cache-dir pipenv pytest

WORKDIR /workspace
