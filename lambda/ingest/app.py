import datetime as dt
import hashlib
import html
import io
import json
import os
from typing import Any, Dict, List, Optional, Tuple

import boto3
import requests
from botocore.exceptions import ClientError
from openpyxl import load_workbook

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
sns = boto3.client("sns")

SOURCE_ID = os.environ.get("SOURCE_ID", "CA_WARN_XLSX")
WARN_CA_URL = os.environ["WARN_CA_URL"]
RAW_BUCKET_NAME = os.environ["RAW_BUCKET_NAME"]
SOURCE_STATE_TABLE = os.environ["SOURCE_STATE_TABLE"]
NOTICES_TABLE = os.environ["NOTICES_TABLE"]
NEW_NOTICE_TOPIC_ARN = os.environ["NEW_NOTICE_TOPIC_ARN"]

source_state_table = dynamodb.Table(SOURCE_STATE_TABLE)
notices_table = dynamodb.Table(NOTICES_TABLE)


def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def fetch_head(url: str) -> Tuple[Optional[str], Optional[str]]:
    # Some servers don't support HEAD reliably; fall back to GET headers only.
    resp = requests.head(url, allow_redirects=True, timeout=30)
    if resp.status_code >= 400:
        resp = requests.get(url, stream=True, timeout=30)
        resp.close()
    etag = resp.headers.get("ETag")
    last_modified = resp.headers.get("Last-Modified")
    return etag, last_modified


def get_source_state(source_id: str) -> Dict[str, Any]:
    resp = source_state_table.get_item(Key={"source_id": source_id})
    return resp.get("Item", {})


def should_download(existing_state: Dict[str, Any], etag: Optional[str], last_modified: Optional[str]) -> bool:
    if not existing_state:
        return True
    old_etag = existing_state.get("etag")
    old_last_modified = existing_state.get("last_modified")
    return (etag and etag != old_etag) or (last_modified and last_modified != old_last_modified)


def download(url: str) -> bytes:
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    return resp.content


def upload_to_s3(content: bytes, etag: Optional[str]) -> str:
    date_prefix = dt.datetime.now(dt.timezone.utc).strftime("%Y/%m/%d")
    etag_seed = (etag or "no-etag").encode("utf-8")
    etag_hash = hashlib.sha256(etag_seed).hexdigest()[:16]
    key = f"raw/CA_WARN_XLSX/{date_prefix}/warn_ca_{etag_hash}.xlsx"
    s3.put_object(
        Bucket=RAW_BUCKET_NAME,
        Key=key,
        Body=content,
        ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    return key


def normalize_header(value: Any) -> str:
    return str(value or "").strip().lower().replace("\n", " ")


def parse_date(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, (int, float)):
        # Excel serial date (1900 date system). Keep values in a sensible range only.
        if 1 <= int(value) <= 80000:
            try:
                excel_epoch = dt.datetime(1899, 12, 30)
                return (excel_epoch + dt.timedelta(days=float(value))).date().isoformat()
            except (OverflowError, ValueError):
                pass
    text = str(value).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%B %d, %Y"):
        try:
            return dt.datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    if text.isdigit():
        serial = int(text)
        if 1 <= serial <= 80000:
            try:
                excel_epoch = dt.datetime(1899, 12, 30)
                return (excel_epoch + dt.timedelta(days=serial)).date().isoformat()
            except (OverflowError, ValueError):
                pass
    return text


def parse_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(str(value).replace(",", "").strip())
    except ValueError:
        return None


def find_col(row: Dict[str, Any], aliases: List[str]) -> Any:
    for alias in aliases:
        if alias in row:
            return row[alias]
    return None


def choose_data_sheet(workbook: Any) -> Any:
    # CA WARN workbook commonly has an index page first and detailed data in another sheet.
    for ws in workbook.worksheets:
        sheet_name = normalize_header(ws.title)
        if "detailed warn report" in sheet_name or "detailed" in sheet_name:
            return ws

    # Fallback: find first sheet that appears to contain the company header.
    for ws in workbook.worksheets:
        for row in ws.iter_rows(min_row=1, max_row=20, values_only=True):
            normalized = [normalize_header(v) for v in row]
            if any("company" in h or "employer" in h for h in normalized):
                return ws

    return workbook.active


def build_notice_id(notice: Dict[str, Any]) -> str:
    key_parts = [
        str(notice.get("state") or ""),
        str(notice.get("company") or ""),
        str(notice.get("notice_date") or ""),
        str(notice.get("city") or ""),
        str(notice.get("employees_affected") or ""),
        str(notice.get("effective_date") or ""),
    ]
    raw = "|".join(key_parts).lower().encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def parse_ca_xlsx(content: bytes) -> List[Dict[str, Any]]:
    wb = load_workbook(io.BytesIO(content), data_only=True)
    ws = choose_data_sheet(wb)

    rows = list(ws.iter_rows(values_only=True))
    header_idx = None
    headers: List[str] = []

    for idx, row in enumerate(rows[:15]):
        normalized = [normalize_header(v) for v in row]
        if any("employer" in h or "company" in h for h in normalized):
            header_idx = idx
            headers = normalized
            break

    if header_idx is None:
        return []

    notices: List[Dict[str, Any]] = []
    for row in rows[header_idx + 1 :]:
        values = list(row)
        if not any(v not in (None, "") for v in values):
            continue

        raw_row: Dict[str, Any] = {}
        for i, h in enumerate(headers):
            if h:
                raw_row[h] = values[i] if i < len(values) else None

        company = find_col(raw_row, ["employer", "employer name", "company", "business name"])
        if not company:
            continue

        notice = {
            "state": "CA",
            "company": html.unescape(str(company).strip()),
            "city": str(find_col(raw_row, ["city"]) or "").strip() or None,
            "county": str(find_col(raw_row, ["county", "county/parish"]) or "").strip() or None,
            "employees_affected": parse_int(
                find_col(
                    raw_row,
                    ["number of employees", "employees", "employees affected", "affected workers", "no. of employees"],
                )
            ),
            "notice_date": parse_date(find_col(raw_row, ["notice date", "received date", "date received", "notice date "])),
            "effective_date": parse_date(find_col(raw_row, ["layoff date", "effective date", "closure date", "effective  date"])),
            "raw_row_json": json.dumps(raw_row, default=str),
        }
        notice["notice_id"] = build_notice_id(notice)
        notices.append(notice)

    return notices


def put_notice_if_new(notice: Dict[str, Any], source_id: str, s3_object_key: str) -> bool:
    item = {
        "notice_id": notice["notice_id"],
        "state": notice.get("state"),
        "company": notice.get("company"),
        "city": notice.get("city"),
        "county": notice.get("county"),
        "employees_affected": notice.get("employees_affected"),
        "notice_date": notice.get("notice_date"),
        "effective_date": notice.get("effective_date"),
        "raw_row_json": notice.get("raw_row_json"),
        "source_id": source_id,
        "s3_object_key": s3_object_key,
        "created_at": utc_now_iso(),
    }
    item = {k: v for k, v in item.items() if v is not None}

    try:
        notices_table.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(notice_id)",
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def emit_new_notice_event(notice: Dict[str, Any]) -> None:
    sns.publish(
        TopicArn=NEW_NOTICE_TOPIC_ARN,
        Message=json.dumps(notice, default=str),
        Subject="new_warn_notice",
    )


def update_source_state(source_id: str, etag: Optional[str], last_modified: Optional[str]) -> None:
    source_state_table.put_item(
        Item={
            "source_id": source_id,
            "etag": etag or "",
            "last_modified": last_modified or "",
            "last_checked_at": utc_now_iso(),
        }
    )


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    force = bool(event.get("force", False))

    etag, last_modified = fetch_head(WARN_CA_URL)
    current_state = get_source_state(SOURCE_ID)

    if not force and not should_download(current_state, etag, last_modified):
        update_source_state(SOURCE_ID, current_state.get("etag"), current_state.get("last_modified"))
        return {"status": "skipped", "reason": "source unchanged"}

    content = download(WARN_CA_URL)
    s3_key = upload_to_s3(content, etag)
    notices = parse_ca_xlsx(content)

    inserted = 0
    for notice in notices:
        is_new = put_notice_if_new(notice, SOURCE_ID, s3_key)
        if is_new:
            inserted += 1
            emit_new_notice_event(notice)

    update_source_state(SOURCE_ID, etag, last_modified)
    return {
        "status": "ok",
        "total_parsed": len(notices),
        "new_inserted": inserted,
        "s3_key": s3_key,
    }
