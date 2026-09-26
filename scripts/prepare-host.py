#!/usr/bin/env python3
"""Enable the Pi memory cgroup without changing other boot parameters."""

import hashlib
import os
from pathlib import Path
import tempfile

BOOT_FILE = Path("/boot/firmware/cmdline.txt")
BACKUP_DIR = Path("/var/lib/pi-k3s-lab/rollback")


def enable_memory(original: str) -> str:
    lines = original.splitlines()
    if len(lines) != 1 or not lines[0].strip():
        raise ValueError("cmdline.txt must contain exactly one non-empty line")
    tokens = lines[0].split()
    for token in tokens:
        if token.startswith("cgroup_disable=") and "memory" in token.split("=", 1)[1].split(","):
            raise ValueError("Explicit cgroup_disable=memory found; review it manually")
        if token.startswith("cgroup_memory=") and token != "cgroup_memory=1":
            raise ValueError("Conflicting cgroup_memory setting; review it manually")
    additions = []
    if "cgroup_memory=1" not in tokens:
        additions.append("cgroup_memory=1")
    enabled = {value for token in tokens if token.startswith("cgroup_enable=")
               for value in token.split("=", 1)[1].split(",")}
    if "memory" not in enabled:
        additions.append("cgroup_enable=memory")
    if not additions:
        return original
    return lines[0].rstrip() + " " + " ".join(additions) + "\n"


def prepare(boot_file: Path, backup_dir: Path) -> bool:
    original = boot_file.read_bytes()
    updated = enable_memory(original.decode("utf-8")).encode("utf-8")
    if updated == original:
        return False
    backup_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    backup = backup_dir / "cmdline.txt"
    # Never overwrite the first known-good boot configuration.
    if backup.exists():
        if backup.read_bytes() != original:
            raise ValueError("An older backup exists and differs; review before changing boot")
    else:
        with backup.open("xb") as stream:
            stream.write(original)
            stream.flush()
            os.fsync(stream.fileno())
    digest = hashlib.sha256(original).hexdigest()
    if hashlib.sha256(backup.read_bytes()).hexdigest() != digest:
        raise RuntimeError("Boot backup verification failed")
    (backup_dir / "cmdline.txt.sha256").write_text(f"{digest}  cmdline.txt\n")
    # Rename within the same filesystem; never truncate the live boot file.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=boot_file.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, boot_file.stat().st_mode & 0o777)
        os.replace(temporary, boot_file)
        os.sync()
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    if boot_file.read_bytes() != updated:
        raise RuntimeError("Boot configuration verification failed")
    return True


if __name__ == "__main__":
    if os.geteuid() != 0:
        raise SystemExit("Run as root on the Raspberry Pi")
    changed = prepare(BOOT_FILE, BACKUP_DIR)
    print("Boot parameters updated; reboot is required." if changed else "Boot parameters unchanged.")
    print(f"Rollback backup (if changed): {BACKUP_DIR}")
    print("After reboot, check: cat /sys/fs/cgroup/cgroup.controllers")
