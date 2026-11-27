import json
import os
import re
import uuid
import base64
import hashlib
import hmac
import secrets
import time
from urllib.parse import quote
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from boto3.dynamodb.conditions import Attr, Key

dynamodb = boto3.resource("dynamodb")
ses = boto3.client("ses")

WATCHLISTS_TABLE = os.environ["WATCHLISTS_TABLE"]
NOTICES_TABLE = os.environ["NOTICES_TABLE"]
NOTIFICATIONS_TABLE = os.environ["NOTIFICATIONS_TABLE"]
USERS_TABLE = os.environ["USERS_TABLE"]
AUTH_RATE_LIMITS_TABLE = os.environ["AUTH_RATE_LIMITS_TABLE"]
AUTH_TOKEN_SECRET = os.environ["AUTH_TOKEN_SECRET"]
AUTH_TOKEN_TTL_SEC = int(os.environ.get("AUTH_TOKEN_TTL_SEC", "86400"))
RESET_TOKEN_TTL_SEC = int(os.environ.get("RESET_TOKEN_TTL_SEC", "3600"))
EMAIL_VERIFICATION_TTL_SEC = int(os.environ.get("EMAIL_VERIFICATION_TTL_SEC", "86400"))
ALERT_SENDER_EMAIL = os.environ["ALERT_SENDER_EMAIL"]
PASSWORD_RESET_FROM_EMAIL = os.environ["PASSWORD_RESET_FROM_EMAIL"]
WEB_APP_BASE_URL = os.environ["WEB_APP_BASE_URL"].rstrip("/")
DEFAULT_STATE = os.environ.get("DEFAULT_STATE", "CA")

watchlists_table = dynamodb.Table(WATCHLISTS_TABLE)
notices_table = dynamodb.Table(NOTICES_TABLE)
notifications_table = dynamodb.Table(NOTIFICATIONS_TABLE)
users_table = dynamodb.Table(USERS_TABLE)
auth_rate_limits_table = dynamodb.Table(AUTH_RATE_LIMITS_TABLE)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def response(status_code: int, body: Dict[str, Any], headers: Dict[str, str] | None = None) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json", **(headers or {})},
        "body": json.dumps(body),
    }


# Counters live in DynamoDB so concurrent Lambda instances share the same limits.
# The source budget is shared across public auth routes; email-sending routes
# have a second, tighter source budget. Account keys include nonexistent emails
# to avoid allowing unlimited guesses for accounts that have not signed up.
AUTH_SOURCE_LIMITS = (("auth_source", 30, 300),)
EMAIL_SOURCE_LIMIT = ("email_source", 10, 3600)
AUTH_ACCOUNT_LIMITS = {
    "signup": ("signup_account", 3, 3600),
    "login": ("login_account", 10, 900),
    "forgot-password": ("email_account", 3, 3600),
    "resend-verification": ("email_account", 3, 3600),
    "verify-email": ("verify_account", 10, 900),
    "reset-password": ("reset_account", 10, 900),
}
EMAIL_SENDING_ROUTES = {"signup", "forgot-password", "resend-verification"}


def consume_auth_budget(budget: str, identity: str, limit: int, window_sec: int) -> Tuple[str, int]:
    now = int(time.time())
    bucket = now // window_sec
    retry_after = max(1, (bucket + 1) * window_sec - now)
    identity_hash = hmac.new(
        AUTH_TOKEN_SECRET.encode("utf-8"),
        f"{budget}:{identity}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    try:
        auth_rate_limits_table.update_item(
            Key={"limit_key": f"{budget}#{bucket}#{identity_hash}"},
            UpdateExpression="SET expires_at = :expires_at ADD request_count :one",
            ConditionExpression=(
                Attr("request_count").not_exists() | Attr("request_count").lt(limit)
            ),
            ExpressionAttributeValues={
                ":expires_at": (bucket + 1) * window_sec + 60,
                ":one": 1,
            },
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return "limited", retry_after
        return "error", retry_after
    except BotoCoreError:
        return "error", retry_after
    return "allowed", retry_after


def enforce_auth_budget(event: Dict[str, Any], route: str, dimension: str, identity: str = "") -> Dict[str, Any] | None:
    if dimension == "source":
        source_ip = str(event.get("requestContext", {}).get("http", {}).get("sourceIp") or "").strip()
        if not source_ip:
            print(json.dumps({"event": "rate_limit_error", "route": route, "dimension": dimension}))
            return response(503, {"message": "authentication temporarily unavailable"})
        budgets = AUTH_SOURCE_LIMITS + ((EMAIL_SOURCE_LIMIT,) if route in EMAIL_SENDING_ROUTES else ())
        identity = source_ip
    else:
        budgets = (AUTH_ACCOUNT_LIMITS[route],)

    for budget, limit, window_sec in budgets:
        result, retry_after = consume_auth_budget(budget, identity, limit, window_sec)
        if result == "allowed":
            continue
        if result == "error":
            print(json.dumps({"event": "rate_limit_error", "route": route, "dimension": dimension}))
            return response(503, {"message": "authentication temporarily unavailable"})

        print(json.dumps({"event": "rate_limit_exceeded", "route": route, "dimension": dimension}))
        if dimension == "account" and route in ("forgot-password", "resend-verification"):
            message = (
                "if that account exists, a reset link has been sent"
                if route == "forgot-password"
                else "if that unverified account exists, a new verification link has been sent"
            )
            return response(200, {"message": message})
        return response(429, {"message": "too many requests; try again later"}, {"Retry-After": str(retry_after)})
    return None


def parse_payload(event: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    raw_body = event.get("body") or "{}"
    if event.get("isBase64Encoded", False):
        return {}, "base64 body is not supported"
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return {}, "invalid JSON body"

    if not isinstance(payload, dict):
        return {}, "JSON body must be an object"

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
        "purpose": "auth",
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

    if not payload.get("sub") or not payload.get("email") or payload.get("purpose") != "auth":
        return {}, "invalid token"

    return payload, ""


def issue_password_reset_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "purpose": "password_reset",
        "exp": int(time.time()) + RESET_TOKEN_TTL_SEC,
    }
    payload_encoded = b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(
        AUTH_TOKEN_SECRET.encode("utf-8"),
        payload_encoded.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return f"{payload_encoded}.{b64url_encode(signature)}"


def validate_password_reset_token(token: str) -> Tuple[Dict[str, Any], str]:
    if not token or "." not in token:
        return {}, "invalid reset token"

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
        return {}, "invalid reset token"

    if not hmac.compare_digest(actual_signature, expected_signature):
        return {}, "invalid reset token"

    if int(payload.get("exp", 0)) <= int(time.time()):
        return {}, "reset token expired"

    if not payload.get("sub") or not payload.get("email") or payload.get("purpose") != "password_reset":
        return {}, "invalid reset token"

    return payload, ""


def issue_email_verification_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "purpose": "email_verification",
        "nonce": secrets.token_urlsafe(16),
        "exp": int(time.time()) + EMAIL_VERIFICATION_TTL_SEC,
    }
    payload_encoded = b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(
        AUTH_TOKEN_SECRET.encode("utf-8"),
        payload_encoded.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return f"{payload_encoded}.{b64url_encode(signature)}"


def validate_email_verification_token(token: str) -> Tuple[Dict[str, Any], str]:
    if not token or "." not in token:
        return {}, "invalid verification link"

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
        return {}, "invalid verification link"

    if not hmac.compare_digest(actual_signature, expected_signature):
        return {}, "invalid verification link"
    if int(payload.get("exp", 0)) <= int(time.time()):
        return {}, "verification link expired"
    if (
        not payload.get("sub")
        or not payload.get("email")
        or payload.get("purpose") != "email_verification"
        or not payload.get("nonce")
    ):
        return {}, "invalid verification link"

    return payload, ""


def hash_verification_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


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


def notice_matches_subscription(notice: Dict[str, Any], state: str, min_employees: int, company_pattern: str) -> bool:
    if state and str(notice.get("state") or "").upper() != state.upper():
        return False

    affected = int(notice.get("employees_affected", 0) or 0)
    if affected < min_employees:
        return False

    haystack = " ".join(
        [
            str(notice.get("company", "")),
            str(notice.get("city", "")),
            str(notice.get("county", "")),
            str(notice.get("state", "")),
        ]
    )
    try:
        return bool(re.search(company_pattern, haystack, flags=re.IGNORECASE))
    except re.error:
        return False


def find_existing_matches(state: str, min_employees: int, company_pattern: str, limit: int = 10) -> Dict[str, Any]:
    start_key = None
    scanned = 0
    matches: list[Dict[str, Any]] = []

    while True:
        kwargs: Dict[str, Any] = {}
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key
        resp = notices_table.scan(**kwargs)
        items = resp.get("Items", [])
        scanned += len(items)

        for item in items:
            if notice_matches_subscription(item, state, min_employees, company_pattern):
                matches.append(
                    {
                        "notice_id": item.get("notice_id"),
                        "company": item.get("company"),
                        "state": item.get("state"),
                        "city": item.get("city"),
                        "employees_affected": int(item.get("employees_affected", 0) or 0),
                        "notice_date": item.get("notice_date"),
                    }
                )
                if len(matches) >= limit:
                    return {"match_count": len(matches), "matches": matches, "scanned": scanned}

        start_key = resp.get("LastEvaluatedKey")
        if not start_key:
            break

    return {"match_count": len(matches), "matches": matches, "scanned": scanned}


def send_password_reset_email(email: str, reset_token: str) -> None:
    reset_url = f"{WEB_APP_BASE_URL}/reset-password.html?token={quote(reset_token, safe='')}"
    subject = "Reset your WARNwatcher password"
    body = (
        "We received a request to reset your password.\n\n"
        f"Reset link: {reset_url}\n\n"
        f"This link expires in {RESET_TOKEN_TTL_SEC // 60} minutes.\n"
        "If you did not request this change, you can ignore this email."
    )
    ses.send_email(
        Source=PASSWORD_RESET_FROM_EMAIL,
        Destination={"ToAddresses": [email]},
        Message={
            "Subject": {"Data": subject},
            "Body": {
                "Text": {"Data": body}
            },
        },
    )


def send_verification_email(email: str, verification_token: str) -> None:
    verification_url = f"{WEB_APP_BASE_URL}/verify-email.html?token={quote(verification_token, safe='')}"
    subject = "Verify your WARNwatcher email"
    body = (
        "Welcome to WARNwatcher. Verify your email address to finish creating your account.\n\n"
        f"Verify and sign in: {verification_url}\n\n"
        f"This link expires in {EMAIL_VERIFICATION_TTL_SEC // 3600} hours.\n"
        "If you did not create this account, you can ignore this email."
    )
    ses.send_email(
        Source=PASSWORD_RESET_FROM_EMAIL,
        Destination={"ToAddresses": [email]},
        Message={
            "Subject": {"Data": subject},
            "Body": {"Text": {"Data": body}},
        },
    )


def write_notification_record(notice_id: str, user_id: str) -> bool:
    try:
        notifications_table.put_item(
            Item={
                "notice_id": notice_id,
                "user_id": user_id,
                "sent_at": utc_now_iso(),
            },
            ConditionExpression="attribute_not_exists(notice_id) AND attribute_not_exists(user_id)",
        )
        return True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def send_immediate_match_email(email: str, company: str, matches: list[Dict[str, Any]]) -> None:
    subject = f"WARNwatcher immediate match: {company}"
    lines = [
        "Your new subscription matched existing WARN notice(s):",
        "",
    ]
    for idx, match in enumerate(matches, start=1):
        lines.extend(
            [
                f"{idx}. {match.get('company', 'Unknown company')}",
                f"   Notice ID: {match.get('notice_id', 'n/a')}",
                f"   State: {match.get('state', 'n/a')}",
                f"   City: {match.get('city', 'n/a')}",
                f"   Employees affected: {match.get('employees_affected', 'n/a')}",
                f"   Notice date: {match.get('notice_date', 'n/a')}",
                "",
            ]
        )
    body = "\n".join(lines).strip()
    ses.send_email(
        Source=ALERT_SENDER_EMAIL,
        Destination={"ToAddresses": [email]},
        Message={
            "Subject": {"Data": subject},
            "Body": {"Text": {"Data": body}},
        },
    )


def handle_signup(event: Dict[str, Any]) -> Dict[str, Any]:
    rate_response = enforce_auth_budget(event, "signup", "source")
    if rate_response is not None:
        return rate_response
    payload, error = parse_payload(event)
    if error:
        return response(400, {"message": error})

    email = str(payload.get("email") or "").strip().lower()
    password = str(payload.get("password") or "")

    if not validate_email(email):
        return response(400, {"message": "a valid email is required"})
    if len(password) < 8:
        return response(400, {"message": "password must be at least 8 characters"})

    rate_response = enforce_auth_budget(event, "signup", "account", email)
    if rate_response is not None:
        return rate_response

    user_id = f"email#{email}"
    verification_token = issue_email_verification_token(user_id, email)

    try:
        users_table.put_item(
            Item={
                "user_id": user_id,
                "email": email,
                "password_hash": hash_password(password),
                "email_verified": False,
                "verification_token_hash": hash_verification_token(verification_token),
                "verification_expires_at": int(time.time()) + EMAIL_VERIFICATION_TTL_SEC,
                "verification_sent_at": int(time.time()),
                "created_at": utc_now_iso(),
            },
            ConditionExpression="attribute_not_exists(user_id)",
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code == "ConditionalCheckFailedException":
            return response(409, {"message": "account already exists"})
        return response(500, {"message": "failed to create account"})

    try:
        send_verification_email(email, verification_token)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "send_failed")
        print(f"verification_email_failed code={code} error={exc}")
        # Permit an immediate resend when the first SES attempt did not leave Lambda.
        try:
            users_table.update_item(
                Key={"user_id": user_id},
                UpdateExpression="SET verification_sent_at = :not_sent",
                ExpressionAttributeValues={":not_sent": 0},
            )
        except ClientError as update_exc:
            print(f"verification_resend_unlock_failed error={update_exc}")
        return response(
            201,
            {
                "message": "account created, but the verification email could not be sent; request a new link",
                "verification_required": True,
                "email_sent": False,
            },
        )

    return response(
        201,
        {
            "message": "account created; check your email to verify and sign in",
            "verification_required": True,
            "email_sent": True,
        },
    )


def handle_verify_email(event: Dict[str, Any]) -> Dict[str, Any]:
    rate_response = enforce_auth_budget(event, "verify-email", "source")
    if rate_response is not None:
        return rate_response
    payload, error = parse_payload(event)
    if error:
        return response(400, {"message": error})

    verification_token = str(payload.get("token") or "").strip()
    token_payload, token_error = validate_email_verification_token(verification_token)
    if token_error:
        return response(400, {"message": token_error})

    rate_response = enforce_auth_budget(event, "verify-email", "account", str(token_payload["sub"]))
    if rate_response is not None:
        return rate_response

    user_id = str(token_payload["sub"])
    email = str(token_payload["email"])
    user = users_table.get_item(Key={"user_id": user_id}).get("Item")
    if not user or str(user.get("email") or "") != email:
        return response(400, {"message": "invalid verification link"})

    if user.get("email_verified") is True:
        return response(400, {"message": "email is already verified; sign in with your password"})

    expected_hash = str(user.get("verification_token_hash") or "")
    if not expected_hash or not hmac.compare_digest(expected_hash, hash_verification_token(verification_token)):
        return response(400, {"message": "invalid or superseded verification link"})
    if int(user.get("verification_expires_at", 0)) <= int(time.time()):
        return response(400, {"message": "verification link expired"})

    try:
        users_table.update_item(
            Key={"user_id": user_id},
            UpdateExpression=(
                "SET email_verified = :verified, email_verified_at = :verified_at "
                "REMOVE verification_token_hash, verification_expires_at, verification_sent_at"
            ),
            ExpressionAttributeValues={
                ":verified": True,
                ":verified_at": utc_now_iso(),
                ":expected_hash": expected_hash,
            },
            ConditionExpression="verification_token_hash = :expected_hash",
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return response(400, {"message": "invalid or already-used verification link"})
        return response(500, {"message": "failed to verify email"})

    access_token = issue_token(user_id, email)
    return response(
        200,
        {
            "message": "email verified",
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": AUTH_TOKEN_TTL_SEC,
            "email": email,
        },
    )


def handle_resend_verification(event: Dict[str, Any]) -> Dict[str, Any]:
    rate_response = enforce_auth_budget(event, "resend-verification", "source")
    if rate_response is not None:
        return rate_response
    payload, error = parse_payload(event)
    if error:
        return response(400, {"message": error})

    email = str(payload.get("email") or "").strip().lower()
    if not validate_email(email):
        return response(400, {"message": "a valid email is required"})

    rate_response = enforce_auth_budget(event, "resend-verification", "account", email)
    if rate_response is not None:
        return rate_response

    generic_message = "if that unverified account exists, a new verification link has been sent"
    user_id = f"email#{email}"
    user = users_table.get_item(Key={"user_id": user_id}).get("Item")
    # A missing flag denotes an account created before verification was introduced.
    if not user or user.get("email_verified") is not False:
        return response(200, {"message": generic_message})

    now = int(time.time())
    if now - int(user.get("verification_sent_at", 0)) < 60:
        return response(200, {"message": generic_message})

    verification_token = issue_email_verification_token(user_id, email)
    try:
        users_table.update_item(
            Key={"user_id": user_id},
            UpdateExpression=(
                "SET verification_token_hash = :token_hash, "
                "verification_expires_at = :expires_at, verification_sent_at = :sent_at"
            ),
            ExpressionAttributeValues={
                ":token_hash": hash_verification_token(verification_token),
                ":expires_at": now + EMAIL_VERIFICATION_TTL_SEC,
                ":sent_at": now,
                ":not_verified": False,
            },
            ConditionExpression="email_verified = :not_verified",
        )
        send_verification_email(email, verification_token)
    except ClientError as exc:
        print(f"resend_verification_failed error={exc}")
        return response(500, {"message": "failed to send verification email"})

    return response(200, {"message": generic_message})


def handle_login(event: Dict[str, Any]) -> Dict[str, Any]:
    rate_response = enforce_auth_budget(event, "login", "source")
    if rate_response is not None:
        return rate_response
    payload, error = parse_payload(event)
    if error:
        return response(400, {"message": error})

    email = str(payload.get("email") or "").strip().lower()
    password = str(payload.get("password") or "")

    if not validate_email(email) or not password:
        return response(400, {"message": "email and password are required"})

    rate_response = enforce_auth_budget(event, "login", "account", email)
    if rate_response is not None:
        return rate_response

    user_id = f"email#{email}"
    result = users_table.get_item(Key={"user_id": user_id})
    user = result.get("Item")
    if not user:
        return response(401, {"message": "invalid credentials"})

    if not verify_password(password, str(user.get("password_hash") or "")):
        return response(401, {"message": "invalid credentials"})

    # Accounts created before verification was introduced have no flag and remain usable.
    if user.get("email_verified") is False:
        return response(403, {"message": "verify your email before signing in", "verification_required": True})

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


def handle_forgot_password(event: Dict[str, Any]) -> Dict[str, Any]:
    rate_response = enforce_auth_budget(event, "forgot-password", "source")
    if rate_response is not None:
        return rate_response
    payload, error = parse_payload(event)
    if error:
        return response(400, {"message": error})

    email = str(payload.get("email") or "").strip().lower()
    if not validate_email(email):
        return response(400, {"message": "a valid email is required"})

    rate_response = enforce_auth_budget(event, "forgot-password", "account", email)
    if rate_response is not None:
        return rate_response

    user_id = f"email#{email}"
    result = users_table.get_item(Key={"user_id": user_id})
    user = result.get("Item")
    if not user:
        # Avoid account enumeration.
        return response(200, {"message": "if that account exists, a reset link has been sent"})

    reset_token = issue_password_reset_token(user_id, email)
    try:
        send_password_reset_email(email, reset_token)
    except ClientError:
        return response(500, {"message": "failed to send reset email"})

    return response(200, {"message": "if that account exists, a reset link has been sent"})


def handle_reset_password(event: Dict[str, Any]) -> Dict[str, Any]:
    rate_response = enforce_auth_budget(event, "reset-password", "source")
    if rate_response is not None:
        return rate_response
    payload, error = parse_payload(event)
    if error:
        return response(400, {"message": error})

    reset_token = str(payload.get("token") or "").strip()
    new_password = str(payload.get("password") or "")
    if len(new_password) < 8:
        return response(400, {"message": "password must be at least 8 characters"})

    token_payload, token_error = validate_password_reset_token(reset_token)
    if token_error:
        return response(400, {"message": token_error})

    rate_response = enforce_auth_budget(event, "reset-password", "account", str(token_payload["sub"]))
    if rate_response is not None:
        return rate_response

    user_id = str(token_payload["sub"])
    try:
        users_table.update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET password_hash = :password_hash, updated_at = :updated_at",
            ExpressionAttributeValues={
                ":password_hash": hash_password(new_password),
                ":updated_at": utc_now_iso(),
            },
            ConditionExpression="attribute_exists(user_id)",
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        print(f"reset_password_update_failed code={code} error={exc}")
        if code == "ConditionalCheckFailedException":
            return response(400, {"message": "invalid reset token"})
        if code in ("AccessDeniedException", "UnauthorizedOperation"):
            return response(500, {"message": "server missing permission to update user password"})
        return response(500, {"message": "failed to reset password"})

    return response(200, {"message": "password reset successful"})


def handle_subscribe(event: Dict[str, Any]) -> Dict[str, Any]:
    token_payload, token_error = authenticate(event)
    if token_error:
        return response(401, {"message": "authentication required"})

    payload, error = parse_payload(event)
    if error:
        return response(400, {"message": error})

    company = str(payload.get("company") or "").strip()
    min_employees = payload.get("min_employees", 0)
    state = str(payload.get("state") or DEFAULT_STATE).upper()

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
            "states": [state],
            "patterns": [re.escape(company)],
            "min_employees": min_employees,
            "created_at": utc_now_iso(),
        }
    )

    existing_match_result = find_existing_matches(state, min_employees, re.escape(company))
    immediate_email_sent = False
    immediate_notified_count = 0
    immediate_email_error = ""
    if existing_match_result["match_count"] > 0:
        for match in existing_match_result["matches"]:
            notice_id = str(match.get("notice_id") or "")
            if notice_id and write_notification_record(notice_id, user_id):
                immediate_notified_count += 1
        try:
            send_immediate_match_email(email, company, existing_match_result["matches"])
            immediate_email_sent = True
        except ClientError as exc:
            immediate_email_error = exc.response.get("Error", {}).get("Code", "send_failed")
            print(f"immediate_match_email_failed code={immediate_email_error} error={exc}")

    return response(
        201,
        {
            "message": "subscription created",
            "user_id": user_id,
            "watch_id": watch_id,
            "existing_match_count": existing_match_result["match_count"],
            "existing_matches": existing_match_result["matches"],
            "immediate_notified_count": immediate_notified_count,
            "immediate_email_sent": immediate_email_sent,
            "immediate_email_error": immediate_email_error,
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


def format_notice(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "notice_id": str(item.get("notice_id") or ""),
        "company": str(item.get("company") or ""),
        "state": str(item.get("state") or ""),
        "city": str(item.get("city") or ""),
        "county": str(item.get("county") or ""),
        "employees_affected": int(item.get("employees_affected", 0) or 0),
        "notice_date": str(item.get("notice_date") or ""),
        "effective_date": str(item.get("effective_date") or ""),
        "received_at": str(item.get("received_at") or ""),
        "source_id": str(item.get("source_id") or ""),
        "s3_object_key": str(item.get("s3_object_key") or ""),
    }


def handle_list_notices(event: Dict[str, Any]) -> Dict[str, Any]:
    token_payload, token_error = authenticate(event)
    if token_error:
        return response(401, {"message": "authentication required"})

    del token_payload  # authenticated access only

    start_key = None
    all_items: list[Dict[str, Any]] = []
    max_items = 2000

    while True:
        kwargs: Dict[str, Any] = {}
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key
        result = notices_table.scan(**kwargs)
        all_items.extend(result.get("Items") or [])
        if len(all_items) >= max_items:
            all_items = all_items[:max_items]
            break
        start_key = result.get("LastEvaluatedKey")
        if not start_key:
            break

    notices = [format_notice(item) for item in all_items]
    notices.sort(
        key=lambda n: (
            str(n.get("notice_date") or ""),
            str(n.get("company") or "").lower(),
            str(n.get("notice_id") or ""),
        ),
        reverse=True,
    )

    return response(200, {"notices": notices, "count": len(notices), "truncated": len(all_items) >= max_items})


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
        if path == "/verify-email":
            return handle_verify_email(event)
        if path == "/resend-verification":
            return handle_resend_verification(event)
        if path == "/forgot-password":
            return handle_forgot_password(event)
        if path == "/reset-password":
            return handle_reset_password(event)
        if path == "/subscribe":
            return handle_subscribe(event)

    if method == "GET":
        if path == "/subscriptions":
            return handle_list_subscriptions(event)
        if path == "/notices":
            return handle_list_notices(event)

    path_parameters = event.get("pathParameters") or {}
    watch_id = str(path_parameters.get("watch_id") or "")
    if watch_id and path.startswith("/subscriptions/"):
        if method == "PUT":
            return handle_update_subscription(event, watch_id)
        if method == "DELETE":
            return handle_delete_subscription(event, watch_id)

    return response(404, {"message": "not found"})
