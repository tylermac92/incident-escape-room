"""ASGI app served by uvicorn. Endpoints arrive with CTL-01."""

from fastapi import FastAPI

app = FastAPI(title="Incident Escape Room controller")
