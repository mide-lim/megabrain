#!/usr/bin/env python3
"""One-time local-TTY bootstrap for GitHub App user-attributed PR creation."""
from __future__ import annotations

import argparse
import getpass
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any


def _load(name: str, filename: str) -> Any:
    path = Path(__file__).with_name(filename)
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError("bootstrap_module_unavailable")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


ATTRIBUTION = _load("megabrain_b42_user_attribution_bootstrap", "github_app_user_attribution.py")
RUNTIME_CONFIG = _load("megabrain_b42_runtime_config_bootstrap", "github_app_runtime_config_bridge.py")


def _result(status: str, failure_code: str | None = None) -> dict[str, Any]:
    return {
        "operation": "bootstrap-user-attribution",
        "status": status,
        "failure_code": failure_code,
        "actor": ATTRIBUTION.EXPECTED_LOGIN if status == "ok" else None,
        "repository": ATTRIBUTION.REPOSITORY if status == "ok" else None,
        "scoped_probe_revoked": status == "ok",
    }


def run(client_id: str, gate_approved: bool) -> dict[str, Any]:
    if not gate_approved:
        return _result("failed", "operational_gate_required")
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return _result("failed", "local_tty_required")
    try:
        runtime = RUNTIME_CONFIG.load_runtime_settings()
        client_secret = getpass.getpass("GitHub App client secret: ")
        device = ATTRIBUTION.request_device_authorization(client_id)
        print(
            f"Authorize MegaBrain Hermes at {device['verification_uri']} "
            f"with code {device['user_code']}",
            flush=True,
        )
        deadline = time.monotonic() + device["expires_in"]
        interval = device["interval"]
        token_body: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            time.sleep(interval)
            status, body = ATTRIBUTION.exchange_device_code(client_id, device["device_code"])
            if status != 200 or not isinstance(body, dict):
                return _result("failed", "device_flow_exchange_failed")
            error = body.get("error")
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                interval += 5
                continue
            if error is not None:
                return _result("failed", "device_flow_authorization_failed")
            token_body = body
            break
        if token_body is None:
            return _result("failed", "device_flow_expired")
        access_token, refresh_token = ATTRIBUTION._extract_user_token_pair(token_body)
        ATTRIBUTION.validate_broad_user_access_token(access_token, runtime.installation_id)
        settings = ATTRIBUTION.UserAttributionSettings(
            client_id=client_id,
            expected_login=ATTRIBUTION.EXPECTED_LOGIN,
            client_secret_path=str(ATTRIBUTION.CLIENT_SECRET_PATH),
            refresh_token_path=str(ATTRIBUTION.REFRESH_TOKEN_PATH),
        )
        scoped = ATTRIBUTION.create_scoped_pr_credential_from_access(
            settings, access_token, client_secret, runtime.installation_id,
        )
        if not ATTRIBUTION.revoke_token_with_secret(client_id, client_secret, scoped.token):
            return _result("failed", "scoped_probe_revocation_failed")
        ATTRIBUTION.persist_bootstrap(client_id, client_secret, refresh_token)
        access_token = ""
        client_secret = ""
        refresh_token = ""
        return _result("ok")
    except ATTRIBUTION.UserAttributionError as exc:
        return _result("failed", exc.code)
    except Exception:
        return _result("failed", "unexpected_failure")


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap user-attributed GitHub App PR creation.")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--operational-gate-approved", action="store_true")
    arguments = parser.parse_args()
    result = run(arguments.client_id, arguments.operational_gate_approved)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
