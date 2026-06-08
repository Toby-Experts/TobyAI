"""Waitlist endpoint for TobyAI.

HTTP-triggered Azure Function (Python v2 model) that receives a waitlist
signup from the static site and stores it as a row in Azure Table Storage.
Deploy this to a Function App in an Australian region (e.g. Australia East)
with a storage account in the same region so signup data stays in Australia.
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone

import azure.functions as func
from azure.data.tables import TableServiceClient, UpdateMode

app = func.FunctionApp()

# Origins allowed to call this endpoint (the live marketing site).
ALLOWED_ORIGINS = {
    "https://tobyai.io",
    "https://www.tobyai.io",
}

TABLE_NAME = "waitlist"


def _connection_string() -> str | None:
    """Storage connection string, read at call time so app settings load first."""
    return os.environ.get("WAITLIST_TABLE_CONNECTION") or os.environ.get("AzureWebJobsStorage")


def _cors_headers(req: func.HttpRequest) -> dict:
    """Echo the request origin if it's allowed, otherwise fall back to the canonical site."""
    origin = req.headers.get("Origin", "")
    allow = origin if origin in ALLOWED_ORIGINS else "https://www.tobyai.io"
    return {
        "Access-Control-Allow-Origin": allow,
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Vary": "Origin",
    }


def _json(payload: dict, status: int, headers: dict) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(payload), status_code=status, mimetype="application/json", headers=headers
    )


@app.route(route="waitlist", methods=["POST", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def waitlist(req: func.HttpRequest) -> func.HttpResponse:
    headers = _cors_headers(req)

    # CORS preflight.
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=headers)

    try:
        body = req.get_json()
    except ValueError:
        return _json({"ok": False, "error": "Invalid JSON."}, 400, headers)

    name = (body.get("name") or "").strip()
    business = (body.get("business") or "").strip()
    email = (body.get("email") or "").strip()
    role = (body.get("role") or body.get("type") or "").strip()

    if not name or not business or not email or "@" not in email or not role:
        return _json({"ok": False, "error": "Missing required fields."}, 400, headers)

    conn = _connection_string()
    if not conn:
        logging.error("No storage connection string configured (WAITLIST_TABLE_CONNECTION).")
        return _json({"ok": False, "error": "Server not configured."}, 500, headers)

    entity = {
        "PartitionKey": "waitlist",
        "RowKey": str(uuid.uuid4()),
        "name": name,
        "business": business,
        "email": email,
        "role": role,
        "tier": (body.get("tier") or "Waitlist").strip(),
        "submitted": (body.get("submitted") or datetime.now(timezone.utc).isoformat()),
    }

    try:
        service = TableServiceClient.from_connection_string(conn)
        table = service.create_table_if_not_exists(TABLE_NAME)
        table.upsert_entity(entity, mode=UpdateMode.MERGE)
    except Exception:
        logging.exception("Failed to write waitlist entry.")
        return _json({"ok": False, "error": "Could not save. Please try again."}, 500, headers)

    logging.info("Stored waitlist signup for %s", email)
    return _json({"ok": True}, 200, headers)
