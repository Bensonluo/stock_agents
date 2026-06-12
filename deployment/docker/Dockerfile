# Multi-stage build for stock-agent application
# 使用 SQLite 作为数据库

# Stage 1: Builder
FROM python:3.11-slim AS builder

# Switch apt to Aliyun mirror (CN network: default deb.debian.org is <10KB/s)
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null

# Install build dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /build

# Copy Poetry files
COPY pyproject.toml poetry.lock* ./

# Configure pip to use Aliyun mirror (CN network: default pypi.org times out on package enumeration)
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && \
    pip config set global.trusted-host mirrors.aliyun.com

# Install Poetry
RUN pip install poetry==1.8.0

# Configure Poetry to not create virtual environments
RUN poetry config virtualenvs.create false

# Install dependencies
# Regenerate lock first if pyproject.toml changed (e.g. when source was added for CN mirror)
RUN poetry lock --no-update
RUN poetry install --no-interaction --no-root --only main

# Stage 2: Production
FROM python:3.11-slim AS production

# Switch apt to Aliyun mirror (CN network: default deb.debian.org is <10KB/s)
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null

# Install runtime dependencies (curl for healthcheck, sqlite3 for debugging)
RUN apt-get update && apt-get install -y \
    curl \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 appuser

# Set working directory
WORKDIR /app

# Copy Python dependencies from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY app ./app

# Create data and logs directories
RUN mkdir -p /app/data /app/logs && chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
