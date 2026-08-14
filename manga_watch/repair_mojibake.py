#!/usr/bin/env python3
"""Repair Latin-1 rendered UTF-8 mojibake in stored state v2 string fields.

The HTTP client used to decode charset-less text/* responses as ISO-8859-1,
so UTF-8 Japanese titles were stored as mojibake (e.g. 科学的に存在しうる
クリーチャー娘の観察日誌 rendered as its latin-1 representation). This module
implements a conservative repair heuristic that only rewrites strings which
round-trip latin-1 -> utf-8 into a CJK-containing string, plus a pure recursive
walker over the state structure that reports every replaced field.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, List, Optional, TextIO, Tuple

from manga_watch.storage import get_state_path, load_state, save_state

# Root prefix of the durable pending daily notification messages. The rendered
# `content` of these messages must never be rewritten (mixed strings, and pure
# mojibake is possible there).
PENDING_MESSAGES_PREFIX = ("discord_delivery", "daily_notification", "pending_messages")


def _contains_cjk(text: str) -> bool:
    return any(
        (0x3040 <= code <= 0x309F)  # Hiragana
        or (0x30A0 <= code <= 0x30FF)  # Katakana
        or (0x4E00 <= code <= 0x9FFF)  # CJK Unified Ideographs
        for code in map(ord, text)
    )


def repair_mojibake(text: str) -> str:
    """Repair a single string if it is a Latin-1 rendering of UTF-8 CJK text.

    Rules, in order:
    1. Non-str input is returned unchanged (malformed state guard).
    2. `text.encode("latin-1")` raising UnicodeEncodeError means the string
       contains code points > U+00FF (normal Japanese/CJK) -> unchanged.
    3. `.decode("utf-8")` on the encoded bytes raising UnicodeDecodeError means
       the bytes are not UTF-8 (e.g. genuine latin-1 text like "café") -> unchanged.
    4. Round-trip producing the identical string -> unchanged.
    5. Result without any CJK char -> unchanged (ASCII URLs, accented European).
    6. Otherwise the result is the repaired string.
    """
    if not isinstance(text, str):
        return text
    try:
        encoded = text.encode("latin-1")
    except UnicodeEncodeError:
        return text
    try:
        decoded = encoded.decode("utf-8")
    except UnicodeDecodeError:
        return text
    if decoded == text:
        return text
    if not _contains_cjk(decoded):
        return text
    return decoded


def _is_excluded_pending_content(path: Tuple[str, ...]) -> bool:
    """True for `discord_delivery.daily_notification.pending_messages.<i>.content`."""
    if len(path) != len(PENDING_MESSAGES_PREFIX) + 2:
        return False
    if path[-1] != "content":
        return False
    if path[:-2] != PENDING_MESSAGES_PREFIX:
        return False
    return path[-2].isdigit()


def _walk(value: object, path: Tuple[str, ...], report: List[Dict[str, object]]) -> object:
    if isinstance(value, dict):
        return {
            key: _walk(item, path + (str(key),), report)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _walk(item, path + (str(index),), report)
            for index, item in enumerate(value)
        ]
    if isinstance(value, str):
        if _is_excluded_pending_content(path):
            return value
        repaired = repair_mojibake(value)
        if repaired != value:
            report.append({"path": ".".join(path), "from": value, "to": repaired})
            return repaired
    return value


def repair_state(state: object) -> Tuple[object, List[Dict[str, object]]]:
    """Recursively repair mojibake strings in a state dict, returning a NEW dict.

    Returns (repaired_state, report) where report lists every replaced field as
    {"path": dot-joined key path with list indices, "from": old, "to": new}.
    Dict keys are never modified and the input state is never mutated.
    """
    report: List[Dict[str, object]] = []
    repaired = _walk(state, (), report)
    return repaired, report


def _affected_work_count(report: List[Dict[str, object]]) -> int:
    """Count distinct `works.<work_id>.*` paths touched by the report."""
    affected = set()
    for entry in report:
        parts = entry["path"].split(".")
        if len(parts) >= 2 and parts[0] == "works":
            affected.add(parts[1])
    return len(affected)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Repair Latin-1 rendered UTF-8 mojibake in stored state v2 string fields.",
    )
    parser.add_argument("--state", default=get_state_path())
    parser.add_argument("--backend", choices=("json", "firestore"), default="json")
    parser.add_argument("--dry-run", action="store_true", help="do not save; print report only")
    parser.add_argument("--json", action="store_true", dest="json_output")
    return parser.parse_args(argv)


def main(
    argv=None,
    *,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    args = parse_args(argv)
    out = stdout or sys.stdout
    err = stderr or sys.stderr
    try:
        if args.backend == "json" and not os.path.exists(args.state):
            raise FileNotFoundError(f"state file not found: {args.state}")
        state = load_state(args.state, backend=args.backend)
        repaired_state, report = repair_state(state)
        if not args.dry_run:
            save_state(repaired_state, args.state, backend=args.backend)
    except Exception as exc:
        print(f"[repair_mojibake] error: {exc}", file=err)
        return 1

    result = {
        "repaired_fields": len(report),
        "affected_works": _affected_work_count(report),
        "dry_run": args.dry_run,
        "state_path": args.state,
        "backend": args.backend,
        "repairs": report,
    }
    if args.json_output:
        print(json.dumps(result, ensure_ascii=False), file=out)
    else:
        verb = "would repair" if args.dry_run else "repaired"
        print(
            f"[repair_mojibake] {verb} {len(report)} fields across "
            f"{result['affected_works']} works",
            file=out,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
