# Copyright 2026 Egor Gladkov (Dezodemius), https://github.com/Dezodemius/dnd-lss-character-generator
# SPDX-License-Identifier: Apache-2.0

"""Смоук-тесты скилла: черновики собираются, готовые примеры проходят проверку, сломанный черновик отклоняется.

Использование: python tools/check.py
"""

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "lss-character"
LSS = SKILL / "scripts" / "lss.py"
FIXTURES = ROOT / "tests" / "fixtures"


def run(*args):
    proc = subprocess.run([sys.executable, str(LSS), *map(str, args)], capture_output=True,
                          text=True, encoding="utf-8")
    return proc.returncode, proc.stdout + proc.stderr


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    failures = []

    def expect(title, ok, output):
        print(f"{'OK  ' if ok else 'FAIL'} {title}")
        if not ok:
            failures.append(title)
            print(output)

    with tempfile.TemporaryDirectory() as tmp:
        drafts = [SKILL / "templates" / "draft-template.json", *sorted(FIXTURES.glob("*.ok.draft.json"))]
        for draft in drafts:
            out = Path(tmp) / (draft.stem + ".lss.json")
            code, output = run("build", draft, "-o", out)
            expect(f"сборка {draft.name}", code == 0 and out.exists(), output)
            if out.exists():
                code, output = run("validate", out)
                expect(f"проверка собранного {draft.name}", code == 0, output)

        for example in sorted((SKILL / "templates").glob("example-*.lss.json")):
            code, output = run("validate", example)
            expect(f"проверка {example.name}", code == 0, output)

        for draft in sorted(FIXTURES.glob("*.bad.draft.json")):
            out = Path(tmp) / (draft.stem + ".lss.json")
            code, output = run("build", draft, "-o", out)
            expect(f"отклонение {draft.name}", code == 1 and not out.exists() and "[X]" in output, output)

    code, output = run("spells", "--edition", "2014", "--class", "wizard", "--level", "0")
    expect("справочник заклинаний", code == 0 and "fire-bolt" in output, output)

    if failures:
        sys.exit(f"\nУпало проверок: {len(failures)}")
    print("\nВсе проверки прошли")


if __name__ == "__main__":
    main()
