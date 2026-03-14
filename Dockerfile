FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends git curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY lib/ lib/
COPY scripts/ scripts/
COPY skills/ skills/
COPY data/ data/

# No ENTRYPOINT — individual services are run via cron or manually
CMD ["bash"]
