"""Component boundaries and fault isolation.

Components live in scripts/gads/<component>/ and may only import the components listed in ALLOWED. A mistake in
one component therefore cannot break components that do not depend on it; these tests prove it by blocking a
component and running the others.
"""
import ast
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
GADS = SCRIPTS / "gads"
sys.path.insert(0, str(SCRIPTS))

# component -> components it may import (besides itself). Lower layers never import higher ones.
ALLOWED = {
    "core": set(),
    "connect": {"core"},
    "setup": {"core"},
    "changes": {"core"},
    "analysis": {"core"},
    "present": {"core", "analysis", "changes"},
    "ai": {"core", "analysis", "present"},
}


def gads_imports(path: Path) -> list[tuple[str, int]]:
    """(imported gads component, line) for every import in the file, top-level or nested."""
    found = []
    for node in ast.walk(ast.parse(path.read_text())):
        names = []
        if isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
        elif isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        for name in names:
            parts = name.split(".")
            if parts[0] == "gads" and len(parts) > 1 and parts[1] in ALLOWED:
                found.append((parts[1], node.lineno))
    return found


class BoundaryTest(unittest.TestCase):
    def test_every_module_belongs_to_a_component(self):
        loose = [p.name for p in GADS.glob("*.py") if p.name != "__init__.py"]
        self.assertEqual(loose, [], "put new modules inside a component package")
        self.assertEqual(sorted(p.name for p in GADS.iterdir() if p.is_dir() and p.name != "__pycache__"),
                         sorted(ALLOWED))

    def test_components_only_import_allowed_components(self):
        violations = []
        for component, allowed in ALLOWED.items():
            for path in (GADS / component).glob("*.py"):
                for target, line in gads_imports(path):
                    if target != component and target not in allowed:
                        violations.append(f"{path.relative_to(ROOT)}:{line} imports gads.{target}")
        self.assertEqual(violations, [])

    def test_components_never_import_command_line_scripts(self):
        scripts = {p.stem for p in SCRIPTS.glob("*.py")}
        bad = []
        for path in GADS.rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                mod = node.module if isinstance(node, ast.ImportFrom) else (
                    node.names[0].name if isinstance(node, ast.Import) else None)
                if mod and mod.split(".")[0] in scripts:
                    bad.append(f"{path.relative_to(ROOT)} imports {mod}")
        self.assertEqual(bad, [])

    def test_dashboard_loads_the_ai_component_only_behind_its_guard(self):
        tree = ast.parse((SCRIPTS / "dashboard.py").read_text())
        top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertFalse([n for n in top if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("gads.ai")])


BLOCKER = """
import sys
class Block:
    def find_spec(self, name, path=None, target=None):
        if any(name == b or name.startswith(b + ".") for b in {blocked!r}):
            raise ImportError("blocked for isolation test: " + name)
sys.meta_path.insert(0, Block())
sys.path.insert(0, {scripts!r})
"""


def import_with_blocked(blocked: list[str], modules: list[str]) -> subprocess.CompletedProcess:
    code = BLOCKER.format(blocked=blocked, scripts=str(SCRIPTS)) + "".join(f"import {m}\n" for m in modules)
    return subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=60)


def modules_of(component: str) -> list[str]:
    return [f"gads.{component}.{p.stem}" for p in (GADS / component).glob("*.py") if p.stem != "__init__"]


class IndependenceTest(unittest.TestCase):
    """Each component imports with every component it does not depend on made unimportable."""

    def test_each_component_works_without_the_others(self):
        for component, allowed in ALLOWED.items():
            blocked = [f"gads.{c}" for c in ALLOWED if c != component and c not in allowed]
            r = import_with_blocked(blocked, modules_of(component))
            self.assertEqual(r.returncode, 0, f"{component} needs a component it should not:\n{r.stderr[-800:]}")

    def test_weekly_analysis_runs_without_presentation_or_ai(self):
        args = ["--snapshot", str(ROOT / "tests" / "fixtures" / "synthetic_weekly_two_weeks.json"),
                "--current", "2026-10-13:2026-10-19", "--previous", "2026-10-06:2026-10-12",
                "--now", "2026-10-25T09:00:00+00:00"]
        code = BLOCKER.format(blocked=["gads.present", "gads.ai"], scripts=str(SCRIPTS)) + f"""
import argparse
from gads.analysis.weekly import build_review
ap = argparse.ArgumentParser()
for flag in ("--snapshot", "--current", "--previous", "--now", "--expected-currency", "--timezone",
             "--conversion-lag-days", "--target-roas", "--target-cpa"):
    ap.add_argument(flag)
review = build_review(ap.parse_args({args!r}))
print(review.ctx.account["current"].cost == __import__("decimal").Decimal("273"))
"""
        r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertEqual(r.stdout.strip(), "True")


class FaultIsolationTest(unittest.TestCase):
    """A failure in an optional part leaves the main outputs intact."""
    WEEKLY = ["--snapshot", str(ROOT / "tests" / "fixtures" / "synthetic_weekly_two_weeks.json"),
              "--current", "2026-10-13:2026-10-19", "--previous", "2026-10-06:2026-10-12",
              "--expected-currency", "EUR", "--now", "2026-10-25T09:00:00+00:00"]

    def test_broken_ai_component_still_builds_the_dashboard(self):
        import dashboard
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(sys.modules, {"gads.ai.dashboard_section": None}), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            code = dashboard.main(self.WEEKLY + ["--out", tmp])
            out = next(Path(tmp).iterdir())
            html = (out / "index.html").read_text()
            self.assertEqual(code, 0)
            self.assertIn("AI analysis is unavailable", html)
            self.assertIn("273.00 EUR", html)  # the engine's numbers are still there
            self.assertFalse((out / "facts.json").exists())
        self.assertIn("AI analysis skipped", err.getvalue())

    def test_invalid_insights_file_does_not_stop_the_dashboard(self):
        import dashboard
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "insights.json"
            bad.write_text("{not json")
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = dashboard.main(self.WEEKLY + ["--insights", str(bad), "--out", tmp + "/o"])
            self.assertEqual(code, 0)
            self.assertIn("AI analysis is unavailable", next(Path(tmp, "o").glob("*/index.html")).read_text())

    def test_broken_page_renderer_keeps_review_data_and_markdown(self):
        import product_review
        import search_terms
        fix = ROOT / "tests" / "fixtures"
        cases = [
            (search_terms, "render_search_dashboard",
             ["--search-terms", str(fix / "synthetic_search_terms.json"), "--keywords", str(fix / "synthetic_keywords.json"),
              "--negatives", str(fix / "synthetic_negatives.json"), "--now", "2026-10-25T09:00:00+00:00"],
             "candidates.json"),
            (product_review, "render_product_dashboard",
             ["--products", str(fix / "synthetic_product_daily.json"), "--now", "2026-10-25T09:00:00+00:00"],
             "products.json"),
        ]
        for module, renderer, args, data_file in cases:
            with self.subTest(module.__name__), tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(module, renderer, side_effect=RuntimeError("synthetic page bug")), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
                code = module.main(args + ["--out", tmp])
                out = next(Path(tmp).iterdir())
                self.assertEqual(code, 0)
                self.assertTrue((out / data_file).exists())
                self.assertTrue((out / "review.md").exists())
                self.assertFalse((out / "dashboard.html").exists())
                self.assertIn("dashboard page skipped", err.getvalue())
                json.loads((out / data_file).read_text())


if __name__ == "__main__":
    unittest.main()
