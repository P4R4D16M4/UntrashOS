#!/usr/bin/env python3
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SKIP = {".git", "build", "inputs"}

patterns = {
    "IPv4 address": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "MAC address": re.compile(r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b"),
    "UUID-like value": re.compile(
        r"\b[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
        r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\b"
    ),
}

violations = []
for path in ROOT.rglob("*.md"):
    if any(part in SKIP for part in path.parts):
        continue
    text = path.read_text(encoding="utf-8", errors="replace")
    for label, pattern in patterns.items():
        for match in pattern.finditer(text):
            violations.append((path.relative_to(ROOT), label, match.group(0)))

if violations:
    print("Potential private or installation-specific values found:")
    for path, label, value in violations:
        print(f"  {path}: {label}: {value}")
    sys.exit(1)

print("Public documentation check passed.")
