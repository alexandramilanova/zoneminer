# Local Docker application: FastAPI serves the API and built frontend.
# Demo analyses are precomputed during the image build.

# --- frontend build stage ---
FROM node:22-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- backend runtime stage ---
FROM python:3.12-slim
WORKDIR /app

# graphviz is used by the legacy Streamlit oracle's visualizations; the API
# itself does not need it, but keeping it makes the image usable for both.
RUN apt-get update && apt-get install -y --no-install-recommends graphviz \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=frontend /build/dist ./frontend/dist

# Run as a non-root user (UID 1000) with a writable application data directory.
ENV ZONE_ANALYTICS_DATA_DIR=/app/var
RUN python tools/precompute_demo.py \
    && useradd -m -u 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 7860
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "7860"]
