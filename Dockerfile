FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi httpx uvicorn

ENV SEARXNG_URL=http://searxng:8080

EXPOSE 8899

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8899", "--workers", "2"]
