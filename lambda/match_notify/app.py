import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List

import boto3
from botocore.exceptions import ClientError

dynamodb = boto3.resource("dynamodb")
ses = boto3.client("ses")

WATCHLISTS_TABLE = os.environ["WATCHLISTS_TABLE"]
NOTIFICATIONS_TABLE = os.environ["NOTIFICATIONS_TABLE"]
ALERT_SENDER_EMAIL = os.environ["ALERT_SENDER_EMAIL"]
DEFAULT_ALERT_RECIPIENT_EMAIL = os.environ["DEFAULT_ALERT_RECIPIENT_EMAIL"]

watchlists_table = dynamodb.Table(WATCHLISTS_TABLE)
notifications_table = dynamodb.Table(NOTIFICATIONS_TABLE)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_watchlists() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    start_key = None

    while True:
        kwargs = {}
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key
        resp = watchlists_table.scan(**kwargs)
        for item in resp.get("Items", []):
            if item.get("is_enabled", True):
                items.append(item)
        start_key = resp.get("LastEvaluatedKey")
        if not start_key:
            break

    return items


def match_notice_to_watchlists(notice: Dict[str, Any], watchlists: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    matches: List[Dict[str, Any]] = []
    haystack = " ".join(
        [
            str(notice.get("company", "")),
            str(notice.get("city", "")),
            str(notice.get("county", "")),
            str(notice.get("state", "")),
        ]
    )

    for w in watchlists:
        states = w.get("states", [])
        if states and notice.get("state") not in states:
            continue

        min_employees = int(w.get("min_employees", 0) or 0)
        affected = int(notice.get("employees_affected", 0) or 0)
        if affected < min_employees:
            continue

        patterns = w.get("patterns", [])
        if not patterns:
            continue

        pattern_hit = False
        for pattern in patterns:
            try:
                if re.search(pattern, haystack, flags=re.IGNORECASE):
                    pattern_hit = True
                    break
            except re.error:
                # Invalid regex is skipped for safety.
                continue

        if pattern_hit:
            matches.append(w)

    return matches


def send_ses_email(to_email: str, subject: str, body: str) -> None:
    ses.send_email(
        Source=ALERT_SENDER_EMAIL,
        Destination={"ToAddresses": [to_email]},
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
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    records = event.get("Records", [])
    watchlists = load_watchlists()
    sent_count = 0

    for record in records:
        msg = record.get("Sns", {}).get("Message", "{}")
        notice = json.loads(msg)
        notice_id = notice.get("notice_id")
        if not notice_id:
            continue

        matching_watchlists = match_notice_to_watchlists(notice, watchlists)
        for w in matching_watchlists:
            user_id = w.get("user_id")
            email = w.get("email") or DEFAULT_ALERT_RECIPIENT_EMAIL
            if not user_id or not email:
                continue

            inserted = write_notification_record(notice_id, user_id)
            if not inserted:
                continue

            subject = f"WARNwatcher match: {notice.get('company', 'Unknown company')}"
            body = (
                f"A new WARN notice matched your watchlist.\n\n"
                f"Company: {notice.get('company')}\n"
                f"State: {notice.get('state')}\n"
                f"City: {notice.get('city')}\n"
                f"County: {notice.get('county')}\n"
                f"Employees affected: {notice.get('employees_affected')}\n"
                f"Notice date: {notice.get('notice_date')}\n"
                f"Effective date: {notice.get('effective_date')}\n"
                f"Notice ID: {notice_id}\n"
            )
            send_ses_email(email, subject, body)
            sent_count += 1

    return {"status": "ok", "sent_count": sent_count, "records": len(records)}
