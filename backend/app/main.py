"""FastAPI entrypoint."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router
from .db import init_db

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s")

app = FastAPI(
    title="Tedlar Lead Agent",
    description="AI lead generation & outreach for DuPont Tedlar Graphics & Signage",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

# Create tables at import time: the API and the CLI runner share one SQLite file,
# and either may be the first to touch it.
init_db()
