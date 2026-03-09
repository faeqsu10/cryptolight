FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir -e .

RUN useradd --create-home appuser
USER appuser

VOLUME ["/app/data"]

ENV TRADE_MODE=paper
ENV LOG_LEVEL=INFO

CMD ["python", "-m", "cryptolight.main"]
