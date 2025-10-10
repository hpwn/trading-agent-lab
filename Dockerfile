FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .
COPY . .
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["tal"]
