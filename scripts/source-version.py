#!/usr/bin/env python3
"""Identify exactly the checked-in files used to build the application image."""

import hashlib
from pathlib import Path

root = Path(__file__).resolve().parents[1]
inputs = ["Dockerfile", ".dockerignore", "app/server.py", "app/index.html", "app/style.css",
          "app/app.js", "app/links.example.json"]
digest = hashlib.sha256()
for name in inputs:
    digest.update(name.encode() + b"\0" + (root / name).read_bytes() + b"\0")
print(digest.hexdigest()[:12])
