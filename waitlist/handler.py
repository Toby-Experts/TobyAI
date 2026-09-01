"""Waitlist signup endpoint.

Accepts one email address, stores it in DynamoDB in ap-southeast-2, and
logs only a hash of the address so an operator reading CloudWatch never
sees who signed up.

The response never says whether an address was already held, so the
endpoint cannot be used to test whether someone is on the list.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)

TABLE_NAME = os.environ["WAITLIST_TABLE"]
ALLOWED_ORIGINS = tuple(
    origin
    for origin in os.environ.get("ALLOWED_ORIGINS", "").split(",")
    if origin
)
RATE_LIMIT_PER_HOUR = int(os.environ.get("RATE_LIMIT_PER_HOUR", "5"))
# Peppers the hashes so a leaked log or key cannot be matched against a
# guessed address by hashing candidates.
HASH_SALT = os.environ["HASH_SALT"]
SIGNUP_TTL_DAYS = int(os.environ.get("SIGNUP_TTL_DAYS", "0"))
SIGNUP_EMAIL_FROM = os.environ.get("SIGNUP_EMAIL_FROM", "")

# The regular expression is deliberately permissive. A receipt is sent on
# first signup, so a bad address fails visibly if it cannot be received.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")
MAX_EMAIL_LENGTH = 254
SIGNUP_RECEIPT_SUBJECT = "You're on the TobyAI waitlist"
SIGNUP_RECEIPT_BODY = """Thanks for signing up. You are on the waitlist for TobyAI.

Access is limited while we onboard the first firms, so this is not a login yet. We will write to you once, when your place is ready, and nothing else in between.

What you are waiting for: TobyAI answers Australian compliance questions with a figure computed in Python from a cited, dated rule, and shows the working. The AI explains what the answer means. It never makes the number up.

Your address is held in Sydney and is never used to train a model. If you would rather we did not hold it, reply to this email with the word remove and we will delete it.

TobyAI
tobyai.io"""

_TABLE = boto3.resource("dynamodb").Table(TABLE_NAME)


def _hashed(value: str) -> str:
    return hashlib.sha256(f"{HASH_SALT}:{value}".encode()).hexdigest()


def _cors_headers(origin: str | None) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-store",
        "Vary": "Origin",
    }
    if origin and origin in ALLOWED_ORIGINS:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Headers"] = "Content-Type"
        headers["Access-Control-Allow-Methods"] = "POST,OPTIONS"
        headers["Access-Control-Max-Age"] = "3600"
    return headers


def _response(
    status: int, body: dict[str, Any], origin: str | None
) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": _cors_headers(origin),
        "body": json.dumps(body),
    }


def _rate_limited(source_ip: str, now: int) -> bool:
    """Count requests per source address per hour, in the same table."""
    if not source_ip:
        return False
    window = now // 3600
    try:
        result = _TABLE.update_item(
            Key={"pk": f"rate#{_hashed(source_ip)}#{window}"},
            UpdateExpression="ADD attempts :one SET expires_at = :ttl",
            ExpressionAttributeValues={":one": 1, ":ttl": (window + 2) * 3600},
            ReturnValues="UPDATED_NEW",
        )
    except ClientError:
        # Fail closed: an unavailable counter must not become an open door.
        LOGGER.exception("rate limit counter failed")
        return True
    attempts = int(result.get("Attributes", {}).get("attempts", 1))
    return attempts > RATE_LIMIT_PER_HOUR


def _store(email: str, source_ip: str, now: int) -> bool:
    item: dict[str, Any] = {
        "pk": f"signup#{_hashed(email)}",
        "email": email,
        "created_at": now,
        "source": "www.tobyai.io",
    }
    if source_ip:
        item["source_ip_hash"] = _hashed(source_ip)
    if SIGNUP_TTL_DAYS:
        item["expires_at"] = now + SIGNUP_TTL_DAYS * 86400
    try:
        _TABLE.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(pk)",
        )
        return True
    except ClientError as error:
        if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        LOGGER.info("already held: %s", item["pk"])
        return False


def _send_receipt(email: str) -> bool:
    if not SIGNUP_EMAIL_FROM:
        return False
    try:
        boto3.client("sesv2").send_email(
            FromEmailAddress=SIGNUP_EMAIL_FROM,
            Destination={"ToAddresses": [email]},
            Content={
                "Simple": {
                    "Subject": {
                        "Data": SIGNUP_RECEIPT_SUBJECT,
                        "Charset": "UTF-8",
                    },
                    "Body": {
                        "Text": {
                            "Data": SIGNUP_RECEIPT_BODY,
                            "Charset": "UTF-8",
                        }
                    },
                }
            },
        )
    except (BotoCoreError, ClientError):
        LOGGER.error("signup receipt failed: %s", _hashed(email))
        return False
    return True


def _mark_notified(email: str, now: int) -> None:
    try:
        _TABLE.update_item(
            Key={"pk": f"signup#{_hashed(email)}"},
            UpdateExpression="SET notified_at = :notified_at",
            ExpressionAttributeValues={":notified_at": now},
        )
    except (BotoCoreError, ClientError):
        LOGGER.error("signup receipt marker failed: %s", _hashed(email))


def handler(event: dict[str, Any], _context: object) -> dict[str, Any]:
    headers = {
        key.lower(): value
        for key, value in (event.get("headers") or {}).items()
    }
    origin = headers.get("origin")
    method = (
        event.get("requestContext", {}).get("http", {}).get("method", "").upper()
    )
    if method == "OPTIONS":
        return _response(204, {}, origin)
    if method != "POST":
        return _response(405, {"error": "method_not_allowed"}, origin)

    try:
        payload = json.loads(event.get("body") or "{}")
    except (ValueError, TypeError):
        return _response(400, {"error": "invalid_request"}, origin)
    if not isinstance(payload, dict):
        return _response(400, {"error": "invalid_request"}, origin)

    # Honeypot: a human never sees this field, so anything in it is a bot.
    # It is answered with the same success shape a person gets, so the bot
    # has no signal to retry against.
    if str(payload.get("company_website") or "").strip():
        LOGGER.info("honeypot filled")
        return _response(202, {"status": "ok"}, origin)

    email = str(payload.get("email") or "").strip().lower()
    if len(email) > MAX_EMAIL_LENGTH or not EMAIL_RE.match(email):
        return _response(400, {"error": "invalid_email"}, origin)

    now = int(time.time())
    source_ip = event.get("requestContext", {}).get("http", {}).get("sourceIp", "")
    if _rate_limited(source_ip, now):
        LOGGER.info("rate limited: %s", _hashed(source_ip))
        return _response(429, {"error": "too_many_requests"}, origin)

    try:
        stored = _store(email, source_ip, now)
    except ClientError:
        LOGGER.exception("waitlist write failed")
        return _response(500, {"error": "storage_unavailable"}, origin)

    LOGGER.info("signup stored: %s", _hashed(email))
    if stored and _send_receipt(email):
        _mark_notified(email, now)
    return _response(202, {"status": "ok"}, origin)
