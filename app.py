"""Vercel entry point: exposes the FastAPI app (backend/main.py) as the serverless function."""
from backend.main import app  # noqa: F401
