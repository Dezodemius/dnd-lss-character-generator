# Copyright 2026 Egor Gladkov (Dezodemius), https://github.com/Dezodemius/dnd-lss-character-generator
# SPDX-License-Identifier: Apache-2.0

"""Собирает скилл в архивы .skill и .zip (одинаковый zip с папкой скилла внутри).

Использование: python tools/package.py [папка-вывода]   (по умолчанию dist/)
"""

import hashlib
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = ROOT / "lss-character"
# Лицензия и NOTICE лежат в корне репозитория, но обязаны ехать с каждой копией скилла.
LEGAL_FILES = ["LICENSE", "NOTICE"]
EXCLUDE_DIRS = {"__pycache__"}
EXCLUDE_SUFFIXES = {".pyc"}
# В архив текст идёт с LF: архив одинаковый с любой машины, где бы ни лежал checkout с CRLF.
TEXT_SUFFIXES = {".md", ".py", ".json", ".txt", ".yml", ".yaml"}
# Фиксированная дата у файлов в архиве, чтобы одинаковое содержимое давало одинаковый архив.
FIXED_DATE = (2026, 1, 1, 0, 0, 0)


def check_frontmatter():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text.replace("\r\n", "\n"), re.S)
    if not m:
        sys.exit("SKILL.md: нет YAML-заголовка")
    head = m.group(1)
    name = re.search(r"^name:\s*(.+)$", head, re.M)
    if not name or name.group(1).strip() != SKILL_DIR.name:
        sys.exit(f"SKILL.md: name должен совпадать с папкой «{SKILL_DIR.name}»")
    if not re.search(r"^description:\s*\S", head, re.M):
        sys.exit("SKILL.md: нет description")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)
    check_frontmatter()
    target = out_dir / f"{SKILL_DIR.name}.skill"
    files = [
        (p, p.relative_to(ROOT).as_posix())
        for p in sorted(SKILL_DIR.rglob("*"))
        if p.is_file()
        and not EXCLUDE_DIRS.intersection(p.relative_to(SKILL_DIR).parts)
        and p.suffix not in EXCLUDE_SUFFIXES
    ]
    for name in LEGAL_FILES:
        if not (ROOT / name).is_file():
            sys.exit(f"нет файла {name} в корне репозитория")
        files.append((ROOT / name, f"{SKILL_DIR.name}/{name}"))
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for p, arcname in files:
            info = zipfile.ZipInfo(arcname, FIXED_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            body = p.read_bytes()
            if p.suffix in TEXT_SUFFIXES or p.name in LEGAL_FILES:
                body = body.replace(b"\r\n", b"\n")
            zf.writestr(info, body)
    # .skill понимает Claude.ai, остальным агентам привычнее .zip - внутри одно и то же.
    zip_copy = target.with_suffix(".zip")
    zip_copy.write_bytes(target.read_bytes())
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    print(f"{target} и {zip_copy.name} ({len(files)} файлов, {target.stat().st_size // 1024} КБ)")
    print(f"sha256: {digest}")


if __name__ == "__main__":
    main()
