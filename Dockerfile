FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1

# Optional but helpful for zoneinfo and consistent market-hours behavior
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*

# Copy full project so src/ is present when we install the package
COPY . .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

ENTRYPOINT ["tal"]
CMD ["orchestrate", "--config", "config/base.yaml"]
