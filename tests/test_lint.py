"""Standard-library lint: every global name a module uses must be defined, imported or built in.

Catches the class of mistake where moving code between modules drops an import (the code only fails when the
affected line runs). Uses symtable, so it needs no third-party linter.
"""
import builtins
import symtable
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = sorted((ROOT / "scripts").rglob("*.py")) + sorted((ROOT / "tests").glob("*.py"))
MODULE_DUNDERS = {"__file__", "__name__", "__doc__", "__spec__", "__loader__", "__package__", "__builtins__",
                  "__annotations__", "__path__"}


def undefined_globals(path: Path) -> list[str]:
    src = path.read_text(encoding="utf-8")
    top = symtable.symtable(src, str(path), "exec")
    defined = {s.get_name() for s in top.get_symbols() if s.is_assigned() or s.is_imported()}
    defined |= set(dir(builtins)) | MODULE_DUNDERS
    missing = set()

    def visit(table):
        for sym in table.get_symbols():
            name = sym.get_name()
            if sym.is_referenced() and (sym.is_global() or table is top) and not sym.is_assigned() \
                    and not sym.is_imported() and name not in defined:
                missing.add(name)
        for child in table.get_children():
            visit(child)

    visit(top)
    return sorted(missing)


class UndefinedNamesTest(unittest.TestCase):
    def test_no_module_uses_an_undefined_global(self):
        problems = {str(p.relative_to(ROOT)): names for p in FILES if (names := undefined_globals(p))}
        self.assertEqual(problems, {})


if __name__ == "__main__":
    unittest.main()
