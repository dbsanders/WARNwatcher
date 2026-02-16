import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

import boto3

dynamodb = boto3.resource("dynamodb")

WATCHLISTS_TABLE = os.environ["WATCHLISTS_TABLE"]
DEFAULT_STATE = os.environ.get("DEFAULT_STATE", "CA")

watchlists_table = dynamodb.Table(WATCHLISTS_TABLE)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def parse_payload(event: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    raw_body = event.get("body") or "{}"
    if event.get("isBase64Encoded", False):
        return {}, "base64 body is not supported"
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return {}, "invalid JSON body"

    return payload, ""


def validate_email(email: str) -> bool:
    # Basic validation for MVP form submission.
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email or ""))


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    method = event.get("requestContext", {}).get("http", {}).get("method")
    path = event.get("rawPath")
    if method != "POST" or path != "/subscribe":
        return response(404, {"message": "not found"})

    payload, error = parse_payload(event)
    if error:
        return response(400, {"message": error})

    email = str(payload.get("email") or "").strip().lower()
    company = str(payload.get("company") or "").strip()
    min_employees = payload.get("min_employees", 0)

    if not validate_email(email):
        return response(400, {"message": "a valid email is required"})
    if not company:
        return response(400, {"message": "company is required"})

    try:
        min_employees = int(min_employees or 0)
    except (TypeError, ValueError):
        return response(400, {"message": "min_employees must be an integer"})

    user_id = f"email#{email}"
    watch_id = str(uuid.uuid4())

    watchlists_table.put_item(
        Item={
            "user_id": user_id,
            "watch_id": watch_id,
            "email": email,
            "is_enabled": True,
            "states": [str(payload.get("state") or DEFAULT_STATE).upper()],
            "patterns": [re.escape(company)],
            "min_employees": min_employees,
            "created_at": utc_now_iso(),
        }
    )

    return response(
        201,
        {
            "message": "subscription created",
            "user_id": user_id,
            "watch_id": watch_id,
        },
    )
