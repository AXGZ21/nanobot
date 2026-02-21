FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    git curl bash procps \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir \
    nanobot-ai \
    fastapi \
    uvicorn[standard] \
    pydantic \
    httpx

COPY start.sh /app/start.sh
COPY webui/ /app/webui/

RUN chmod +x /app/start.sh

EXPOSE 8080

CMD ["/app/start.sh"]