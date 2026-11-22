# Build from this folder: docker build -t phantom-duelist .
# The match runs it with no network, a read-only root (writable /tmp), 1 CPU,
# 512 MB, and the map mounted at /arena.
FROM python:3.13-slim
WORKDIR /bot
COPY mechfight.py bot.py ./
COPY combat ./combat
ENTRYPOINT ["python3", "-u", "/bot/bot.py"]
