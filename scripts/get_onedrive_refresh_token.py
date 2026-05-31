from __future__ import annotations

import argparse
import json
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a delegated Microsoft Graph refresh token for personal OneDrive access."
    )
    parser.add_argument("client_id", help="Application (client) ID from Microsoft Entra app registration.")
    parser.add_argument("--authority", default="common", help="Use common, consumers, or a tenant ID.")
    args = parser.parse_args()

    endpoint = f"https://login.microsoftonline.com/{args.authority}/oauth2/v2.0"
    device = _post_json(
        f"{endpoint}/devicecode",
        {"client_id": args.client_id, "scope": "offline_access Files.Read"},
    )
    print(device["message"])
    print("Waiting for Microsoft sign-in approval...")

    interval = int(device.get("interval") or 5)
    while True:
        time.sleep(interval)
        try:
            token = _post_json(
                f"{endpoint}/token",
                {
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "client_id": args.client_id,
                    "device_code": device["device_code"],
                },
            )
        except HTTPError as exc:
            payload = json.loads(exc.read().decode("utf-8"))
            error = payload.get("error")
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                interval += 5
                continue
            raise
        refresh_token = token.get("refresh_token")
        if not refresh_token:
            raise SystemExit("Microsoft did not return a refresh token. Confirm that offline_access was granted.")
        print("\nStore the following value as the GitHub repository secret ONEDRIVE_REFRESH_TOKEN:")
        print(refresh_token)
        print("\nDo not commit this token or share it in chat.")
        return 0


def _post_json(url: str, form: dict[str, str]) -> dict:
    request = Request(
        url,
        data=urlencode(form).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
