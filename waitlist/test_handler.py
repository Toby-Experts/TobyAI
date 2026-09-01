from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from typing import Any

import pytest
from botocore.exceptions import ClientError

os.environ["AWS_DEFAULT_REGION"] = "ap-southeast-2"
os.environ["AWS_EC2_METADATA_DISABLED"] = "true"
os.environ["WAITLIST_TABLE"] = "test-waitlist"
os.environ["ALLOWED_ORIGINS"] = "https://www.tobyai.io,https://tobyai.io"
os.environ["RATE_LIMIT_PER_HOUR"] = "5"
os.environ["HASH_SALT"] = "fixed-test-salt"
os.environ.pop("SIGNUP_EMAIL_FROM", None)

from waitlist import handler as waitlist


def _client_error(code: str, operation: str) -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": "test failure"}},
        operation,
    )


class FakeTable:
    def __init__(self) -> None:
        self.put_calls: list[dict[str, Any]] = []
        self.update_calls: list[dict[str, Any]] = []
        self.update_result: dict[str, Any] = {"Attributes": {"attempts": 1}}
        self.put_error: ClientError | None = None
        self.update_error: ClientError | None = None

    def put_item(self, **kwargs: Any) -> None:
        self.put_calls.append(kwargs)
        if self.put_error is not None:
            raise self.put_error

    def update_item(self, **kwargs: Any) -> dict[str, Any]:
        self.update_calls.append(kwargs)
        if self.update_error is not None:
            raise self.update_error
        return self.update_result


class FakeSes:
    def __init__(self) -> None:
        self.send_calls: list[dict[str, Any]] = []
        self.send_error: ClientError | None = None

    def send_email(self, **kwargs: Any) -> None:
        self.send_calls.append(kwargs)
        if self.send_error is not None:
            raise self.send_error


@pytest.fixture
def table(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeTable]:
    fake = FakeTable()
    monkeypatch.setattr(waitlist, "_TABLE", fake)
    yield fake


@pytest.fixture
def ses(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeSes]:
    fake = FakeSes()
    monkeypatch.setattr(waitlist.boto3, "client", lambda service: fake)
    yield fake


def _event(
    method: str,
    body: dict[str, Any] | None = None,
    *,
    origin: str = "https://www.tobyai.io",
    source_ip: str = "203.0.113.10",
) -> dict[str, Any]:
    return {
        "headers": {"Origin": origin},
        "requestContext": {
            "http": {"method": method, "sourceIp": source_ip},
        },
        "body": json.dumps(body) if body is not None else None,
    }


def _status(response: dict[str, Any]) -> int:
    return int(response["statusCode"])


def test_valid_signup_stores_salted_hash_and_returns_202(
    table: FakeTable,
) -> None:
    email = "person@example.com"

    response = waitlist.handler(
        _event("POST", {"email": email, "company_website": ""}),
        None,
    )

    assert _status(response) == 202
    item = table.put_calls[0]["Item"]
    assert item["pk"] == f"signup#{waitlist._hashed(email)}"
    assert item["email"] == email
    assert email not in item["pk"]


def test_first_signup_sends_receipt(
    table: FakeTable,
    ses: FakeSes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = "person@example.com"
    monkeypatch.setattr(waitlist, "SIGNUP_EMAIL_FROM", "developer@tobyai.io")

    response = waitlist.handler(_event("POST", {"email": email}), None)

    assert _status(response) == 202
    assert len(ses.send_calls) == 1
    send = ses.send_calls[0]
    assert send["FromEmailAddress"] == "developer@tobyai.io"
    assert send["Destination"] == {"ToAddresses": [email]}
    content = send["Content"]["Simple"]
    assert content["Subject"]["Data"] == "You're on the TobyAI waitlist"
    body = content["Body"]["Text"]["Data"]
    assert body == waitlist.SIGNUP_RECEIPT_BODY
    assert body.splitlines()[-1] == "tobyai.io"
    assert table.update_calls[-1]["Key"] == {
        "pk": f"signup#{waitlist._hashed(email)}"
    }
    assert ":notified_at" in table.update_calls[-1]["ExpressionAttributeValues"]


def test_repeat_signup_sends_nothing(
    table: FakeTable,
    ses: FakeSes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(waitlist, "SIGNUP_EMAIL_FROM", "developer@tobyai.io")
    table.put_error = _client_error("ConditionalCheckFailedException", "PutItem")

    response = waitlist.handler(_event("POST", {"email": "repeat@example.com"}), None)

    assert _status(response) == 202
    assert ses.send_calls == []
    assert table.update_calls
    assert all("notified_at" not in call.get("UpdateExpression", "") for call in table.update_calls)


def test_receipt_failure_still_returns_202_without_notification_marker(
    table: FakeTable,
    ses: FakeSes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = "receipt-failure@example.com"
    monkeypatch.setattr(waitlist, "SIGNUP_EMAIL_FROM", "developer@tobyai.io")
    ses.send_error = _client_error("MessageRejected", "SendEmail")

    response = waitlist.handler(_event("POST", {"email": email}), None)

    assert _status(response) == 202
    assert len(ses.send_calls) == 1
    assert all("notified_at" not in call.get("UpdateExpression", "") for call in table.update_calls)


def test_unset_sender_sends_nothing(table: FakeTable, ses: FakeSes) -> None:
    response = waitlist.handler(
        _event("POST", {"email": "no-receipt@example.com"}), None
    )

    assert _status(response) == 202
    assert ses.send_calls == []


def test_invalid_address_stores_nothing(table: FakeTable) -> None:
    response = waitlist.handler(_event("POST", {"email": "not-an-address"}), None)

    assert _status(response) == 400
    assert table.update_calls == []
    assert table.put_calls == []


def test_address_over_254_characters_stores_nothing(table: FakeTable) -> None:
    email = f"{'a' * 245}@example.com"

    response = waitlist.handler(_event("POST", {"email": email}), None)

    assert len(email) > 254
    assert _status(response) == 400
    assert table.update_calls == []
    assert table.put_calls == []


def test_honeypot_returns_success_without_storing(table: FakeTable) -> None:
    response = waitlist.handler(
        _event(
            "POST",
            {"email": "bot@example.com", "company_website": "https://bot.example"},
        ),
        None,
    )

    assert _status(response) == 202
    assert table.update_calls == []
    assert table.put_calls == []


def test_duplicate_returns_success(table: FakeTable) -> None:
    table.put_error = _client_error(
        "ConditionalCheckFailedException",
        "PutItem",
    )

    response = waitlist.handler(
        _event("POST", {"email": "duplicate@example.com"}),
        None,
    )

    assert _status(response) == 202


def test_rate_limit_above_limit_returns_429(table: FakeTable) -> None:
    table.update_result = {"Attributes": {"attempts": 6}}

    response = waitlist.handler(
        _event("POST", {"email": "limited@example.com"}),
        None,
    )

    assert _status(response) == 429
    assert table.put_calls == []


def test_rate_limit_counter_error_fails_closed(table: FakeTable) -> None:
    table.update_error = _client_error("InternalServerError", "UpdateItem")

    response = waitlist.handler(
        _event("POST", {"email": "counter-error@example.com"}),
        None,
    )

    assert _status(response) == 429
    assert table.put_calls == []


def test_storage_error_returns_500(table: FakeTable) -> None:
    table.put_error = _client_error("ServiceUnavailable", "PutItem")

    response = waitlist.handler(
        _event("POST", {"email": "storage-error@example.com"}),
        None,
    )

    assert _status(response) == 500


def test_options_returns_204_and_get_returns_405(table: FakeTable) -> None:
    options = waitlist.handler(_event("OPTIONS"), None)
    get = waitlist.handler(_event("GET"), None)

    assert _status(options) == 204
    assert _status(get) == 405


def test_cors_headers_are_limited_to_allowed_origins(table: FakeTable) -> None:
    allowed = waitlist.handler(
        _event("OPTIONS", origin="https://tobyai.io"),
        None,
    )
    unlisted = waitlist.handler(
        _event("OPTIONS", origin="https://unlisted.example"),
        None,
    )

    assert allowed["headers"]["Access-Control-Allow-Origin"] == "https://tobyai.io"
    assert "Access-Control-Allow-Origin" not in unlisted["headers"]


def test_no_log_record_contains_a_raw_email_address(
    table: FakeTable,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    emails = {
        "valid@example.com",
        "honeypot@example.com",
        "duplicate-log@example.com",
        "limited-log@example.com",
        "counter-log@example.com",
        "storage-log@example.com",
    }

    waitlist.handler(_event("POST", {"email": "valid@example.com"}), None)
    waitlist.handler(
        _event(
            "POST",
            {"email": "honeypot@example.com", "company_website": "filled"},
        ),
        None,
    )
    table.put_error = _client_error("ConditionalCheckFailedException", "PutItem")
    waitlist.handler(_event("POST", {"email": "duplicate-log@example.com"}), None)
    table.update_result = {"Attributes": {"attempts": 6}}
    waitlist.handler(_event("POST", {"email": "limited-log@example.com"}), None)
    table.update_result = {"Attributes": {"attempts": 1}}
    table.update_error = _client_error("InternalServerError", "UpdateItem")
    waitlist.handler(_event("POST", {"email": "counter-log@example.com"}), None)
    table.update_error = None
    table.put_error = _client_error("ServiceUnavailable", "PutItem")
    waitlist.handler(_event("POST", {"email": "storage-log@example.com"}), None)

    messages = [record.getMessage() for record in caplog.records]
    assert all(email not in message for email in emails for message in messages)
    assert sum(waitlist._hashed(email) in message for email in emails for message in messages) >= 2
