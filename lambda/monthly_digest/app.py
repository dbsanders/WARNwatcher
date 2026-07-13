import logging
import os
import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List

import boto3
from botocore.exceptions import ClientError


logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
ses = boto3.client("ses")

WATCHLISTS_TABLE = os.environ["WATCHLISTS_TABLE"]
ALERT_SENDER_EMAIL = os.environ["ALERT_SENDER_EMAIL"]
watchlists_table = dynamodb.Table(WATCHLISTS_TABLE)


def load_enabled_subscriptions() -> List[Dict[str, Any]]:
    """Load every enabled subscription, following DynamoDB scan pagination."""
    items: List[Dict[str, Any]] = []
    start_key = None

    while True:
        kwargs: Dict[str, Any] = {}
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key

        response = watchlists_table.scan(**kwargs)
        items.extend(item for item in response.get("Items", []) if item.get("is_enabled", True))
        start_key = response.get("LastEvaluatedKey")
        if not start_key:
            return items


def company_name(subscription: Dict[str, Any]) -> str:
    company = str(subscription.get("company") or "").strip()
    if company:
        return company

    # Older records may only contain the escaped literal pattern created by the API.
    patterns = subscription.get("patterns") or []
    pattern = str(patterns[0]).strip() if patterns else ""
    return re.sub(r"\\(.)", r"\1", pattern)


def group_companies_by_email(subscriptions: Iterable[Dict[str, Any]]) -> Dict[str, List[str]]:
    grouped: Dict[str, Dict[str, str]] = defaultdict(dict)

    for subscription in subscriptions:
        email = str(subscription.get("email") or "").strip().lower()
        company = company_name(subscription)
        if not email or not company:
            continue
        grouped[email].setdefault(company.casefold(), company)

    return {
        email: sorted(companies.values(), key=str.casefold)
        for email, companies in grouped.items()
    }


def build_email_body(companies: List[str]) -> str:
    noun = "company" if len(companies) == 1 else "companies"
    lines = [
        "Here is your monthly WARNwatcher subscription summary.",
        "",
        f"You are subscribed to {len(companies)} {noun}:",
        "",
        *(f"- {company}" for company in companies),
        "",
        "You will continue to receive an alert when a matching WARN notice is found.",
    ]
    return "\n".join(lines)


def send_digest(to_email: str, companies: List[str]) -> None:
    ses.send_email(
        Source=ALERT_SENDER_EMAIL,
        Destination={"ToAddresses": [to_email]},
        Message={
            "Subject": {"Data": "Your monthly WARNwatcher subscriptions"},
            "Body": {"Text": {"Data": build_email_body(companies)}},
        },
    )


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    subscriptions = load_enabled_subscriptions()
    subscribers = group_companies_by_email(subscriptions)
    sent_count = 0
    failed_count = 0

    logger.info(
        "monthly_digest start enabled_subscriptions=%s subscribers=%s",
        len(subscriptions),
        len(subscribers),
    )

    # A failure for one subscriber must not prevent summaries for everyone else.
    for email, companies in subscribers.items():
        try:
            send_digest(email, companies)
            sent_count += 1
            logger.info("monthly_digest sent email=%s companies=%s", email, len(companies))
        except ClientError as exc:
            failed_count += 1
            error_code = exc.response.get("Error", {}).get("Code", "send_failed")
            logger.exception("monthly_digest failed email=%s code=%s", email, error_code)

    result = {
        "status": "ok" if failed_count == 0 else "partial_failure",
        "subscriptions": len(subscriptions),
        "subscribers": len(subscribers),
        "sent_count": sent_count,
        "failed_count": failed_count,
    }
    logger.info("monthly_digest done result=%s", result)
    return result
