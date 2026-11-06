"""Entry point: `uvicorn mockloom_api.asgi:app`. Importing this module creates the database."""

from .main import create_app

app = create_app()
