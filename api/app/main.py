"""TobyAI waitlist API.

A small FastAPI service that accepts a waitlist signup from the marketing site
and stores it as a row in Azure Table Storage. It is packaged as a container
and deployed to Azure Container Apps in an Australian region, so signup data
stays in Australia.
"""

import logging
import os
import uuid
from datetime import datetime, timezone

from azure.data.tables import TableServiceClient, UpdateMode
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field

logger = logging.getLogger("waitlist")

# Origins allowed to call this API (the live marketing site).
ALLOWED_ORIGINS = [
    "https://tobyai.io",
    "https://www.tobyai.io",
]
TABLE_NAME = "waitlist"

app = FastAPI(title="TobyAI Waitlist API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


class Signup(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    business: str = Field(min_length=1, max_length=200)
    email: EmailStr
    role: str = Field(min_length=1, max_length=100)
    tier: str = Field(default="Waitlist", max_length=50)
    submitted: str | None = None


def _connection_string() -> str | None:
    return os.environ.get("WAITLIST_TABLE_CONNECTION")


@app.get("/healthz")
def healthz() -> dict:
    """Liveness probe for Container Apps."""
    return {"ok": True}


@app.post("/waitlist")
def join_waitlist(signup: Signup) -> dict:
    conn = _connection_string()
    if not conn:
        logger.error("WAITLIST_TABLE_CONNECTION is not set.")
        raise HTTPException(status_code=500, detail="Server not configured.")

    entity = {
        "PartitionKey": "waitlist",
        "RowKey": str(uuid.uuid4()),
        "name": signup.name.strip(),
        "business": signup.business.strip(),
        "email": str(signup.email).strip(),
        "role": signup.role.strip(),
        "tier": signup.tier.strip(),
        "submitted": signup.submitted or datetime.now(timezone.utc).isoformat(),
    }

    try:
        service = TableServiceClient.from_connection_string(conn)
        table = service.create_table_if_not_exists(TABLE_NAME)
        table.upsert_entity(entity, mode=UpdateMode.MERGE)
    except Exception:
        logger.exception("Failed to write waitlist entry.")
        raise HTTPException(status_code=502, detail="Could not save. Please try again.")

    logger.info("Stored waitlist signup for %s", entity["email"])
    return {"ok": True}
