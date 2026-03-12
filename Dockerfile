FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

RUN useradd --create-home appuser

COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir -e . && \
    apt-get purge -y gcc && apt-get autoremove -y

USER appuser

VOLUME ["/app/data"]

ENV TRADE_MODE=paper
ENV LOG_LEVEL=INFO

CMD ["python", "-m", "cryptolight"]
