import json
import os
import re
import uuid
import base64
import hashlib
import hmac
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

import boto3
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")

WATCHLISTS_TABLE = os.environ["WATCHLISTS_TABLE"]
USERS_TABLE = os.environ["USERS_TABLE"]
AUTH_TOKEN_SECRET = os.environ["AUTH_TOKEN_SECRET"]
AUTH_TOKEN_TTL_SEC = int(os.environ.get("AUTH_TOKEN_TTL_SEC", "86400"))
DEFAULT_STATE = os.environ.get("DEFAULT_STATE", "CA")

watchlists_table = dynamodb.Table(WATCHLISTS_TABLE)
users_table = dynamodb.Table(USERS_TABLE)


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


def b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def b64url_decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    iterations = 200000
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iteration_text, salt, expected_digest = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iteration_text)
    except (ValueError, TypeError):
        return False

    actual_digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()
    return hmac.compare_digest(actual_digest, expected_digest)


def issue_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "exp": int(time.time()) + AUTH_TOKEN_TTL_SEC,
    }
    payload_encoded = b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(
        AUTH_TOKEN_SECRET.encode("utf-8"),
        payload_encoded.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return f"{payload_encoded}.{b64url_encode(signature)}"


def validate_token(token: str) -> Tuple[Dict[str, Any], str]:
    if not token or "." not in token:
        return {}, "invalid token"

    payload_encoded, signature_encoded = token.split(".", 1)
    expected_signature = hmac.new(
        AUTH_TOKEN_SECRET.encode("utf-8"),
        payload_encoded.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    try:
        actual_signature = b64url_decode(signature_encoded)
        payload = json.loads(b64url_decode(payload_encoded).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return {}, "invalid token"

    if not hmac.compare_digest(actual_signature, expected_signature):
        return {}, "invalid token"

    if int(payload.get("exp", 0)) <= int(time.time()):
        return {}, "token expired"

    if not payload.get("sub") or not payload.get("email"):
        return {}, "invalid token"

    return payload, ""


def get_bearer_token(event: Dict[str, Any]) -> str:
    headers = event.get("headers") or {}
    auth_header = headers.get("authorization") or headers.get("Authorization") or ""
    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return ""
    return parts[1].strip()


def authenticate(event: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    token = get_bearer_token(event)
    return validate_token(token)


def pattern_to_company(pattern: str) -> str:
    if not pattern:
        return ""
    return re.sub(r"\\(.)", r"\1", pattern)


def format_subscription(item: Dict[str, Any]) -> Dict[str, Any]:
    patterns = item.get("patterns") or []
    states = item.get("states") or []
    company = str(item.get("company") or "")
    if not company:
        company = pattern_to_company(str(patterns[0] if patterns else ""))

    return {
        "watch_id": item.get("watch_id"),
        "email": item.get("email"),
        "company": company,
        "state": str(states[0] if states else DEFAULT_STATE),
        "min_employees": int(item.get("min_employees", 0)),
        "is_enabled": bool(item.get("is_enabled", True)),
        "created_at": item.get("created_at"),
    }


def parse_bool(value: Any) -> Tuple[bool, str]:
    if isinstance(value, bool):
        return value, ""
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes"):
            return True, ""
        if lowered in ("false", "0", "no"):
            return False, ""
    return False, "is_enabled must be a boolean"


def handle_signup(event: Dict[str, Any]) -> Dict[str, Any]:
    payload, error = parse_payload(event)
    if error:
        return response(400, {"message": error})

    email = str(payload.get("email") or "").strip().lower()
    password = str(payload.get("password") or "")

    if not validate_email(email):
        return response(400, {"message": "a valid email is required"})
    if len(password) < 8:
        return response(400, {"message": "password must be at least 8 characters"})

    user_id = f"email#{email}"

    try:
        users_table.put_item(
            Item={
                "user_id": user_id,
                "email": email,
                "password_hash": hash_password(password),
                "created_at": utc_now_iso(),
            },
            ConditionExpression="attribute_not_exists(user_id)",
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code == "ConditionalCheckFailedException":
            return response(409, {"message": "account already exists"})
        return response(500, {"message": "failed to create account"})

    return response(201, {"message": "account created"})


def handle_login(event: Dict[str, Any]) -> Dict[str, Any]:
    payload, error = parse_payload(event)
    if error:
        return response(400, {"message": error})

    email = str(payload.get("email") or "").strip().lower()
    password = str(payload.get("password") or "")

    if not validate_email(email) or not password:
        return response(400, {"message": "email and password are required"})

    user_id = f"email#{email}"
    result = users_table.get_item(Key={"user_id": user_id})
    user = result.get("Item")
    if not user:
        return response(401, {"message": "invalid credentials"})

    if not verify_password(password, str(user.get("password_hash") or "")):
        return response(401, {"message": "invalid credentials"})

    token = issue_token(user_id, email)
    return response(
        200,
        {
            "message": "login successful",
            "access_token": token,
            "token_type": "Bearer",
            "expires_in": AUTH_TOKEN_TTL_SEC,
            "email": email,
        },
    )


def handle_subscribe(event: Dict[str, Any]) -> Dict[str, Any]:
    token_payload, token_error = authenticate(event)
    if token_error:
        return response(401, {"message": "authentication required"})

    payload, error = parse_payload(event)
    if error:
        return response(400, {"message": error})

    company = str(payload.get("company") or "").strip()
    min_employees = payload.get("min_employees", 0)

    if not company:
        return response(400, {"message": "company is required"})

    try:
        min_employees = int(min_employees or 0)
    except (TypeError, ValueError):
        return response(400, {"message": "min_employees must be an integer"})

    user_id = str(token_payload["sub"])
    email = str(token_payload["email"])
    watch_id = str(uuid.uuid4())

    watchlists_table.put_item(
        Item={
            "user_id": user_id,
            "watch_id": watch_id,
            "email": email,
            "is_enabled": True,
            "company": company,
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


def handle_list_subscriptions(event: Dict[str, Any]) -> Dict[str, Any]:
    token_payload, token_error = authenticate(event)
    if token_error:
        return response(401, {"message": "authentication required"})

    user_id = str(token_payload["sub"])
    result = watchlists_table.query(KeyConditionExpression=Key("user_id").eq(user_id))
    items = result.get("Items") or []
    subscriptions = [format_subscription(item) for item in items]

    return response(200, {"subscriptions": subscriptions})


def handle_update_subscription(event: Dict[str, Any], watch_id: str) -> Dict[str, Any]:
    token_payload, token_error = authenticate(event)
    if token_error:
        return response(401, {"message": "authentication required"})

    payload, error = parse_payload(event)
    if error:
        return response(400, {"message": error})

    company = payload.get("company")
    state = payload.get("state")
    min_employees = payload.get("min_employees")
    is_enabled = payload.get("is_enabled")

    update_parts = []
    expression_attribute_values: Dict[str, Any] = {}
    expression_attribute_names: Dict[str, str] = {}

    if company is not None:
        company = str(company).strip()
        if not company:
            return response(400, {"message": "company cannot be empty"})
        update_parts.extend(["company = :company", "patterns = :patterns"])
        expression_attribute_values[":company"] = company
        expression_attribute_values[":patterns"] = [re.escape(company)]

    if state is not None:
        state = str(state).strip().upper()
        if len(state) != 2:
            return response(400, {"message": "state must be a 2-letter code"})
        update_parts.append("states = :states")
        expression_attribute_values[":states"] = [state]

    if min_employees is not None:
        try:
            min_employees = int(min_employees)
        except (TypeError, ValueError):
            return response(400, {"message": "min_employees must be an integer"})
        if min_employees < 0:
            return response(400, {"message": "min_employees must be >= 0"})
        update_parts.append("min_employees = :min_employees")
        expression_attribute_values[":min_employees"] = min_employees

    if is_enabled is not None:
        parsed_is_enabled, bool_error = parse_bool(is_enabled)
        if bool_error:
            return response(400, {"message": bool_error})
        update_parts.append("is_enabled = :is_enabled")
        expression_attribute_values[":is_enabled"] = parsed_is_enabled

    if not update_parts:
        return response(400, {"message": "no editable fields provided"})

    expression_attribute_names["#uid"] = "user_id"
    expression_attribute_names["#wid"] = "watch_id"

    try:
        result = watchlists_table.update_item(
            Key={"user_id": str(token_payload["sub"]), "watch_id": watch_id},
            UpdateExpression=f"SET {', '.join(update_parts)}",
            ExpressionAttributeValues=expression_attribute_values,
            ExpressionAttributeNames=expression_attribute_names,
            ConditionExpression="attribute_exists(#uid) AND attribute_exists(#wid)",
            ReturnValues="ALL_NEW",
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code == "ConditionalCheckFailedException":
            return response(404, {"message": "subscription not found"})
        return response(500, {"message": "failed to update subscription"})

    return response(200, {"message": "subscription updated", "subscription": format_subscription(result["Attributes"])})


def handle_delete_subscription(event: Dict[str, Any], watch_id: str) -> Dict[str, Any]:
    token_payload, token_error = authenticate(event)
    if token_error:
        return response(401, {"message": "authentication required"})

    try:
        watchlists_table.delete_item(
            Key={"user_id": str(token_payload["sub"]), "watch_id": watch_id},
            ConditionExpression="attribute_exists(user_id) AND attribute_exists(watch_id)",
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code == "ConditionalCheckFailedException":
            return response(404, {"message": "subscription not found"})
        return response(500, {"message": "failed to delete subscription"})

    return response(200, {"message": "subscription deleted", "watch_id": watch_id})


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    method = event.get("requestContext", {}).get("http", {}).get("method")
    path = str(event.get("rawPath") or "")
    if method == "POST":
        if path == "/signup":
            return handle_signup(event)
        if path == "/login":
            return handle_login(event)
        if path == "/subscribe":
            return handle_subscribe(event)

    if method == "GET" and path == "/subscriptions":
        return handle_list_subscriptions(event)

    path_parameters = event.get("pathParameters") or {}
    watch_id = str(path_parameters.get("watch_id") or "")
    if watch_id and path.startswith("/subscriptions/"):
        if method == "PUT":
            return handle_update_subscription(event, watch_id)
        if method == "DELETE":
            return handle_delete_subscription(event, watch_id)

    return response(404, {"message": "not found"})
