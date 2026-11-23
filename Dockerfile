# Works on Render, Railway, Fly.io, Hugging Face Spaces (Docker) and any Docker host.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV HOST=0.0.0.0 PORT=8000 ALLOW_PUBLIC_DASHBOARD=true SEED_DEMO_ON_START=true WHATSAPP_MODE=simulated
EXPOSE 8000
CMD ["python", "run.py"]
