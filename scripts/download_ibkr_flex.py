from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


FLEX_BASE_URL = "https://gdcdyn.interactivebrokers.com/Universal/servlet"
DEFAULT_OUTPUT_DIR = ".cloud-statements"


def main() -> int:
    parser = argparse.ArgumentParser(description="Download IBKR Flex Query XML reports.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--token", default=os.getenv("IBKR_FLEX_TOKEN", "").strip())
    parser.add_argument("--activity-query-id", default=os.getenv("IBKR_ACTIVITY_QUERY_ID", "").strip())
    parser.add_argument("--trade-confirm-query-id", default=os.getenv("IBKR_TRADE_CONFIRM_QUERY_ID", "").strip())
    parser.add_argument("--max-wait-seconds", type=int, default=60)
    parser.add_argument("--query-delay-seconds", type=int, default=30)
    parser.add_argument("--rate-limit-retries", type=int, default=1)
    parser.add_argument("--rate-limit-wait-seconds", type=int, default=60)
    parser.add_argument("--transient-retries", type=int, default=2)
    parser.add_argument("--transient-wait-seconds", type=int, default=90)
    args = parser.parse_args()

    if not args.token:
        raise SystemExit("IBKR_FLEX_TOKEN is required.")
    queries = [
        ("activity", args.activity_query_id),
        ("trade-confirm", args.trade_confirm_query_id),
    ]
    queries = [(label, query_id) for label, query_id in queries if query_id]
    if not queries:
        raise SystemExit("At least one of IBKR_ACTIVITY_QUERY_ID or IBKR_TRADE_CONFIRM_QUERY_ID is required.")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    downloaded = []
    failures = []
    for index, (label, query_id) in enumerate(queries):
        if index and args.query_delay_seconds > 0:
            time.sleep(args.query_delay_seconds)
        try:
            destination = _download_query_with_retry(
                token=args.token,
                label=label,
                query_id=query_id,
                output_dir=output_dir,
                max_wait_seconds=args.max_wait_seconds,
                rate_limit_retries=args.rate_limit_retries,
                rate_limit_wait_seconds=args.rate_limit_wait_seconds,
                transient_retries=args.transient_retries,
                transient_wait_seconds=args.transient_wait_seconds,
            )
        except RuntimeError as exc:
            failures.append(f"{label}: {exc}")
            print(f"IBKR Flex {label} query failed; continuing if another query succeeded: {exc}", file=sys.stderr)
            continue
        downloaded.append(destination)
        print(f"IBKR Flex {label} statement downloaded: {destination.name}")
    if not downloaded:
        details = " | ".join(failures) if failures else "No files were downloaded."
        raise SystemExit(f"IBKR Flex download failed; no statement files available. {details}")
    if failures:
        print(f"Downloaded {len(downloaded)} IBKR Flex statement file(s); {len(failures)} query failed.")
        for failure in failures:
            print(f"IBKR Flex partial failure: {failure}", file=sys.stderr)
        return 0
    print(f"Downloaded {len(downloaded)} IBKR Flex statement file(s).")
    return 0


def _download_query_with_retry(
    *,
    token: str,
    label: str,
    query_id: str,
    output_dir: Path,
    max_wait_seconds: int,
    rate_limit_retries: int,
    rate_limit_wait_seconds: int,
    transient_retries: int,
    transient_wait_seconds: int,
) -> Path:
    max_attempts = max(0, rate_limit_retries, transient_retries) + 1
    rate_limit_retry_count = 0
    transient_retry_count = 0
    for attempt in range(1, max_attempts + 1):
        try:
            reference = request_flex_statement(token, query_id)
            content = download_flex_statement(token, reference, max_wait_seconds=max_wait_seconds)
            destination = output_dir / f"ibkr-{label}-{query_id}.xml"
            destination.write_bytes(content)
            return destination
        except RuntimeError as exc:
            message = str(exc)
            if rate_limit_retry_count < max(0, rate_limit_retries) and _looks_like_rate_limit_error(message):
                rate_limit_retry_count += 1
                print(
                    f"IBKR Flex {label} query was rate limited; retrying in {rate_limit_wait_seconds}s.",
                    file=sys.stderr,
                )
                time.sleep(max(0, rate_limit_wait_seconds))
                continue
            if transient_retry_count < max(0, transient_retries) and _looks_like_transient_generation_error(message):
                transient_retry_count += 1
                print(
                    f"IBKR Flex {label} query was not ready to generate; retrying in {transient_wait_seconds}s.",
                    file=sys.stderr,
                )
                time.sleep(max(0, transient_wait_seconds))
                continue
            raise
    raise RuntimeError("IBKR Flex query failed unexpectedly.")


def request_flex_statement(token: str, query_id: str) -> str:
    params = {"t": token, "q": query_id, "v": "3"}
    payload = _request_xml(f"{FLEX_BASE_URL}/FlexStatementService.SendRequest?{urlencode(params)}")
    status = _xml_text(payload, "Status")
    if status and status.lower() != "success":
        raise RuntimeError(f"IBKR Flex request failed: {status} {_xml_text(payload, 'ErrorMessage')}")
    reference = _xml_text(payload, "ReferenceCode")
    if not reference:
        raise RuntimeError("IBKR Flex request did not return a ReferenceCode.")
    return reference


def download_flex_statement(token: str, reference: str, *, max_wait_seconds: int = 60) -> bytes:
    params = {"t": token, "q": reference, "v": "3"}
    url = f"{FLEX_BASE_URL}/FlexStatementService.GetStatement?{urlencode(params)}"
    deadline = time.monotonic() + max_wait_seconds
    while True:
        content = _request_bytes(url)
        if _looks_like_pending_response(content) and time.monotonic() < deadline:
            time.sleep(5)
            continue
        if _looks_like_pending_response(content):
            raise RuntimeError("IBKR Flex statement was not ready before timeout.")
        return content


def _request_xml(url: str) -> ET.Element:
    content = _request_bytes(url)
    try:
        return ET.fromstring(content)
    except ET.ParseError as exc:
        raise RuntimeError("IBKR Flex service returned invalid XML.") from exc


def _request_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "macro-regime-radar/1.0"})
    try:
        with urlopen(request, timeout=30) as response:
            return response.read()
    except (HTTPError, URLError) as exc:
        raise RuntimeError(f"IBKR Flex request failed: {exc}") from exc


def _xml_text(root: ET.Element, tag: str) -> str:
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == tag:
            return (element.text or "").strip()
    return ""


def _looks_like_pending_response(content: bytes) -> bool:
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return False
    status = _xml_text(root, "Status").lower()
    if status in {"warn", "warning", "pending"}:
        return True
    message = (_xml_text(root, "ErrorMessage") or _xml_text(root, "Message")).lower()
    return "not ready" in message or "please try again" in message


def _looks_like_rate_limit_error(message: str) -> bool:
    text = message.lower()
    return "too many requests" in text or "rate limit" in text


def _looks_like_transient_generation_error(message: str) -> bool:
    text = message.lower()
    return (
        "could not be generated at this time" in text
        or "please try again shortly" in text
        or "temporarily unavailable" in text
    )


if __name__ == "__main__":
    raise SystemExit(main())
