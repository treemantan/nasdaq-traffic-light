from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
DEFAULT_FOLDER = "Trading/Revolut Transaction Statement"
DEFAULT_PATTERN = "trading-account-statement_*.csv"


@dataclass(frozen=True)
class GraphConfig:
    client_id: str
    folder_path: str
    pattern: str
    tenant_id: str = ""
    client_secret: str = ""
    refresh_token: str = ""
    user_id: str = ""

    @property
    def auth_mode(self) -> str:
        if self.client_secret and self.tenant_id and self.user_id:
            return "client_credentials"
        if self.refresh_token:
            return "refresh_token"
        raise ValueError(
            "OneDrive authentication is incomplete. Configure either "
            "ONEDRIVE_TENANT_ID + ONEDRIVE_CLIENT_ID + ONEDRIVE_CLIENT_SECRET + ONEDRIVE_USER_ID, "
            "or ONEDRIVE_CLIENT_ID + ONEDRIVE_REFRESH_TOKEN."
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download Revolut statement CSV files from OneDrive via Microsoft Graph."
    )
    parser.add_argument("--output-dir", default=".cloud-statements")
    parser.add_argument("--folder-path", default=os.getenv("ONEDRIVE_FOLDER_PATH") or DEFAULT_FOLDER)
    parser.add_argument("--pattern", default=os.getenv("ONEDRIVE_STATEMENT_PATTERN") or DEFAULT_PATTERN)
    parser.add_argument(
        "--latest-per-account-folder",
        action="store_true",
        default=_env_flag("ONEDRIVE_USE_LATEST_PER_ACCOUNT_FOLDER"),
        help="Treat direct child folders as separate accounts and download only their latest matching CSV.",
    )
    parser.add_argument(
        "--import-portfolio",
        action="store_true",
        help="Run scripts/import_revolut_statement.py after downloading the selected CSV files.",
    )
    args = parser.parse_args()

    config = _config_from_env(args.folder_path, args.pattern)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    token = _acquire_access_token(config)
    items = _select_statement_items(token, config, args.latest_per_account_folder)
    if not items:
        raise SystemExit(
            f"No Revolut statement CSV matched {config.pattern!r} inside OneDrive folder {config.folder_path!r}."
        )

    downloaded = [_download_item(token, config, item, output_dir) for item in items]
    print(f"Downloaded {len(downloaded)} OneDrive statement file(s).")
    for path in downloaded:
        print(f"Statement: {path.name}")

    if args.import_portfolio:
        command = [sys.executable, "scripts/import_revolut_statement.py", *map(str, downloaded)]
        subprocess.run(command, check=True)
        print("Cloud portfolio import completed.")
    return 0


def _config_from_env(folder_path: str, pattern: str) -> GraphConfig:
    client_id = os.getenv("ONEDRIVE_CLIENT_ID", "").strip()
    if not client_id:
        raise ValueError("ONEDRIVE_CLIENT_ID is required.")
    return GraphConfig(
        client_id=client_id,
        tenant_id=os.getenv("ONEDRIVE_TENANT_ID", "").strip(),
        client_secret=os.getenv("ONEDRIVE_CLIENT_SECRET", "").strip(),
        refresh_token=os.getenv("ONEDRIVE_REFRESH_TOKEN", "").strip(),
        user_id=os.getenv("ONEDRIVE_USER_ID", "").strip(),
        folder_path=folder_path.strip().strip("/"),
        pattern=pattern.strip() or DEFAULT_PATTERN,
    )


def _acquire_access_token(config: GraphConfig) -> str:
    if config.auth_mode == "client_credentials":
        endpoint = f"https://login.microsoftonline.com/{quote(config.tenant_id)}/oauth2/v2.0/token"
        payload = {
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        }
    else:
        authority = config.tenant_id or "common"
        endpoint = f"https://login.microsoftonline.com/{quote(authority)}/oauth2/v2.0/token"
        payload = {
            "client_id": config.client_id,
            "refresh_token": config.refresh_token,
            "scope": "offline_access Files.Read",
            "grant_type": "refresh_token",
        }
    response = _request_json(endpoint, method="POST", form=payload)
    token = str(response.get("access_token") or "")
    if not token:
        raise RuntimeError("Microsoft identity platform did not return an access token.")
    if config.auth_mode == "refresh_token" and response.get("refresh_token"):
        print(
            "Microsoft issued a rotated refresh token. The existing GitHub secret may continue working, "
            "but refresh ONEDRIVE_REFRESH_TOKEN if a later run reports an authorization failure."
        )
    return token


def _select_statement_items(token: str, config: GraphConfig, latest_per_account_folder: bool) -> list[dict[str, Any]]:
    children = _list_children(token, config, config.folder_path)
    if latest_per_account_folder:
        folders = [item for item in children if item.get("folder") is not None]
        selected = []
        for folder in folders:
            nested_path = f"{config.folder_path}/{folder['name']}"
            matches = _matching_files(_list_children(token, config, nested_path), config.pattern)
            if matches:
                selected.append(_latest(matches))
        if selected:
            return selected
    return _matching_files(children, config.pattern)


def _list_children(token: str, config: GraphConfig, folder_path: str) -> list[dict[str, Any]]:
    url = _children_url(config, folder_path)
    items: list[dict[str, Any]] = []
    while url:
        response = _request_json(url, token=token)
        items.extend(response.get("value") or [])
        url = str(response.get("@odata.nextLink") or "")
    return items


def _children_url(config: GraphConfig, folder_path: str) -> str:
    owner = f"/users/{quote(config.user_id)}" if config.auth_mode == "client_credentials" else "/me"
    encoded_path = quote(folder_path.strip("/"), safe="/")
    return (
        f"{GRAPH_ROOT}{owner}/drive/root:/{encoded_path}:/children"
        "?$select=id,name,file,folder,lastModifiedDateTime,size"
    )


def _matching_files(items: list[dict[str, Any]], pattern: str) -> list[dict[str, Any]]:
    return [
        item
        for item in items
        if item.get("file") is not None and fnmatch.fnmatch(str(item.get("name") or ""), pattern)
    ]


def _latest(items: list[dict[str, Any]]) -> dict[str, Any]:
    return max(items, key=lambda item: str(item.get("lastModifiedDateTime") or ""))


def _download_item(token: str, config: GraphConfig, item: dict[str, Any], output_dir: Path) -> Path:
    item_id = quote(str(item["id"]))
    request = Request(f"{GRAPH_ROOT}/me/drive/items/{item_id}/content", headers=_auth_headers(token))
    # App-only Graph calls cannot use /me.
    if config.auth_mode == "client_credentials":
        user_id = quote(config.user_id)
        request = Request(f"{GRAPH_ROOT}/users/{user_id}/drive/items/{item_id}/content", headers=_auth_headers(token))
    destination = _unique_destination(output_dir, Path(str(item["name"])).name)
    try:
        with urlopen(request, timeout=30) as response:
            destination.write_bytes(response.read())
    except (HTTPError, URLError) as exc:
        raise RuntimeError(f"Failed to download OneDrive item {item.get('name')!r}: {exc}") from exc
    return destination


def _unique_destination(output_dir: Path, file_name: str) -> Path:
    destination = output_dir / file_name
    suffix = 2
    while destination.exists():
        destination = output_dir / f"{Path(file_name).stem}-{suffix}{Path(file_name).suffix}"
        suffix += 1
    return destination


def _request_json(
    url: str,
    *,
    method: str = "GET",
    form: dict[str, str] | None = None,
    token: str = "",
) -> dict[str, Any]:
    data = urlencode(form).encode("utf-8") if form is not None else None
    headers = {"Content-Type": "application/x-www-form-urlencoded"} if form is not None else {}
    headers.update(_auth_headers(token))
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Microsoft Graph request failed with HTTP {exc.code}: {detail[:500]}") from exc
    except URLError as exc:
        raise RuntimeError(f"Microsoft Graph request failed: {exc}") from exc


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
