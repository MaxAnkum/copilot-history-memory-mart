FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PROJECT_ROOT=/app

WORKDIR /app

# System deps (optional, keep slim)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
 && rm -rf /var/lib/apt/lists/*

# Copy only sources for faster builds
COPY memory_artifacts/ ./memory_artifacts/
COPY README.md ./
COPY requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt || true

# Default envs can be overridden at runtime
ENV COMPACT_MODE=1 \
    ONTOLOGY_BUILD=0 \
    ONTOLOGY_SUGGEST=0 \
    ONTOLOGY_AUTO_APPLY=0 \
    ONTOLOGY_SOURCES_SUGGEST=0

# Default command
CMD ["python", "memory_artifacts/pipeline.py"]
