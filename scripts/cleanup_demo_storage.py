#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
STORAGE_ROOT = ROOT_DIR / "apps" / "api" / "storage"


def _iter_paths_for_cleanup(root: Path) -> list[Path]:
    return sorted(root.rglob("*"), key=lambda path: len(path.parts), reverse=True)


def cleanup_storage(root: Path) -> tuple[int, int]:
    if not root.exists():
        return 0, 0

    deleted_files = 0
    deleted_dirs = 0

    for path in _iter_paths_for_cleanup(root):
        if path.is_file() and path.name != ".gitkeep":
            path.unlink()
            deleted_files += 1

    for path in _iter_paths_for_cleanup(root):
        if path.is_dir():
            try:
                path.rmdir()
                deleted_dirs += 1
            except OSError:
                pass

    return deleted_files, deleted_dirs


def main() -> int:
    deleted_files, deleted_dirs = cleanup_storage(STORAGE_ROOT)
    print(f"storage_root={STORAGE_ROOT}")
    print(f"deleted_files={deleted_files}")
    print(f"deleted_dirs={deleted_dirs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
