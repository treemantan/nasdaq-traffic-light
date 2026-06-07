from __future__ import annotations

import argparse
import os
import time
from pathlib import Path
from typing import Any
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
    for label, query_id in queries:
        reference = request_flex_statement(args.token, query_id)
        content = download_flex_statement(args.token, reference, max_wait_seconds=args.max_wait_seconds)
        destination = output_dir / f"ibkr-{label}-{query_id}.xml"
        destination.write_bytes(content)
        downloaded.append(destination)
        print(f"IBKR Flex {label} statement downloaded: {destination.name}")
    print(f"Downloaded {len(downloaded)} IBKR Flex statement file(s).")
    return 0


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


if __name__ == "__main__":
    raise SystemExit(main())
