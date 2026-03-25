#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Dict, Optional

import requests
from nacl.signing import SigningKey


def load_payload(*, payload_json: Optional[str], payload_file: Optional[str]) -> Dict[str, Any]:
    if bool(payload_json) == bool(payload_file):
        raise ValueError("set exactly one of --payload-json or --payload-file")
    raw = payload_json
    if payload_file is not None:
        with open(payload_file, "r", encoding="utf-8") as handle:
            raw = handle.read()
    payload = json.loads(raw or "")
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    return payload


def canonical_body(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def signed_headers(
    *,
    body: bytes,
    private_key_hex: str,
    timestamp: str,
    invalidate_signature: bool = False,
) -> Dict[str, str]:
    signing_key = SigningKey(bytes.fromhex(private_key_hex))
    signature = signing_key.sign(timestamp.encode("utf-8") + body).signature.hex()
    if invalidate_signature:
        replacement = "0" if signature[0] != "0" else "1"
        signature = replacement + signature[1:]
    return {
        "Content-Type": "application/json",
        "X-Signature-Ed25519": signature,
        "X-Signature-Timestamp": timestamp,
    }


def post_signed_interaction(
    *,
    url: str,
    payload: Dict[str, Any],
    private_key_hex: str,
    timestamp: Optional[str] = None,
    invalidate_signature: bool = False,
    timeout: int = 10,
    session: Optional[requests.Session] = None,
) -> Dict[str, Any]:
    body = canonical_body(payload)
    request_timestamp = timestamp or str(int(time.time()))
    headers = signed_headers(
        body=body,
        private_key_hex=private_key_hex,
        timestamp=request_timestamp,
        invalidate_signature=invalidate_signature,
    )
    client = session or requests.Session()
    response = client.post(
        url,
        data=body,
        headers=headers,
        timeout=timeout,
        allow_redirects=False,
    )
    return {
        "statusCode": response.status_code,
        "timestamp": request_timestamp,
        "body": response.text,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Post a Discord interaction payload signed with an Ed25519 private key.",
    )
    parser.add_argument("--url", required=True, help="Cloud Run Service URL")
    parser.add_argument("--private-key", required=True, help="hex-encoded Ed25519 private key seed")
    parser.add_argument("--payload-json", help="inline JSON object payload")
    parser.add_argument("--payload-file", help="path to JSON object payload")
    parser.add_argument("--timestamp", help="override timestamp header")
    parser.add_argument("--invalidate-signature", action="store_true", help="flip one nibble after signing")
    parser.add_argument("--timeout", type=int, default=10, help="HTTP timeout seconds")
    parser.add_argument("--expect-status", type=int, help="exit non-zero when status does not match")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = load_payload(payload_json=args.payload_json, payload_file=args.payload_file)
        result = post_signed_interaction(
            url=args.url,
            payload=payload,
            private_key_hex=args.private_key,
            timestamp=args.timestamp,
            invalidate_signature=args.invalidate_signature,
            timeout=args.timeout,
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(json.dumps(result, ensure_ascii=False))
    if args.expect_status is not None and result["statusCode"] != args.expect_status:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
