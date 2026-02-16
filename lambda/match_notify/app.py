import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

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
logger = logging.getLogger()
logger.setLevel(logging.INFO)


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


def notice_matches_watchlist(notice: Dict[str, Any], watchlist: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    states = watchlist.get("states", [])
    if states and notice.get("state") not in states:
        return False, "state_mismatch"

    min_employees = int(watchlist.get("min_employees", 0) or 0)
    affected = int(notice.get("employees_affected", 0) or 0)
    if affected < min_employees:
        return False, "below_min_employees"

    patterns = watchlist.get("patterns", [])
    if not patterns:
        return False, "missing_patterns"

    haystack = " ".join(
        [
            str(notice.get("company", "")),
            str(notice.get("city", "")),
            str(notice.get("county", "")),
            str(notice.get("state", "")),
        ]
    )

    had_invalid_pattern = False
    for pattern in patterns:
        try:
            if re.search(pattern, haystack, flags=re.IGNORECASE):
                return True, None
        except re.error:
            # Invalid regex is skipped for safety.
            had_invalid_pattern = True
            continue

    if had_invalid_pattern:
        return False, "invalid_or_no_pattern_match"
    return False, "no_pattern_match"


def match_notice_to_watchlists(notice: Dict[str, Any], watchlists: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    matches: List[Dict[str, Any]] = []
    for w in watchlists:
        is_match, _ = notice_matches_watchlist(notice, w)
        if is_match:
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
    no_notice_id_count = 0

    logger.info(
        "match_notify start records=%s enabled_watchlists=%s",
        len(records),
        len(watchlists),
    )

    for idx, record in enumerate(records):
        msg = record.get("Sns", {}).get("Message", "{}")
        notice = json.loads(msg)
        notice_id = notice.get("notice_id")
        if not notice_id:
            no_notice_id_count += 1
            logger.warning("skip record_index=%s reason=missing_notice_id", idx)
            continue

        logger.info(
            "processing notice_id=%s company=%s state=%s employees_affected=%s",
            notice_id,
            notice.get("company"),
            notice.get("state"),
            notice.get("employees_affected"),
        )

        reason_counts: Dict[str, int] = {}
        matching_watchlists: List[Dict[str, Any]] = []
        for w in watchlists:
            is_match, reason = notice_matches_watchlist(notice, w)
            if is_match:
                matching_watchlists.append(w)
            else:
                reason_key = reason or "unknown_non_match"
                reason_counts[reason_key] = reason_counts.get(reason_key, 0) + 1

        logger.info(
            "notice_id=%s matches=%s non_match_breakdown=%s",
            notice_id,
            len(matching_watchlists),
            reason_counts,
        )

        for w in matching_watchlists:
            user_id = w.get("user_id")
            email = w.get("email") or DEFAULT_ALERT_RECIPIENT_EMAIL
            if not user_id or not email:
                logger.info(
                    "skip notice_id=%s reason=missing_user_or_email user_id=%s email_present=%s",
                    notice_id,
                    user_id,
                    bool(email),
                )
                continue

            inserted = write_notification_record(notice_id, user_id)
            if not inserted:
                logger.info("skip notice_id=%s user_id=%s reason=already_notified", notice_id, user_id)
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
            logger.info("sent notice_id=%s user_id=%s email=%s", notice_id, user_id, email)

    logger.info(
        "match_notify done records=%s missing_notice_id=%s sent_count=%s",
        len(records),
        no_notice_id_count,
        sent_count,
    )
    return {"status": "ok", "sent_count": sent_count, "records": len(records)}
