# Mise en ligne : Hugging Face Spaces (sdk: docker, port 7860), Render, Fly.io…
FROM caddy:2 AS caddy

FROM python:3.12-slim
COPY --from=caddy /usr/bin/caddy /usr/local/bin/caddy

RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH" \
    PORT=7860 \
    DASHBOARD_HOST=127.0.0.1 \
    PYTHONUNBUFFERED=1
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user . .

EXPOSE 7860
CMD ["python", "lancer_cloud.py"]
