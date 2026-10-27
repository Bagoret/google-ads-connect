"""Component boundaries and fault isolation (see docs/architecture.md).

The engine is organised features-first: shared foundations (core, ui, connect) and one package per feature
(weekly, search_terms, products, changes, onboarding, ai). Three rules, checked statically and by importing each
component with everything it does not depend on blocked:
  1. a component imports only the components listed for it in ALLOWED (shared layers never import features);
  2. features are independent of each other (the only exception: ai extends the weekly review);
  3. inside a feature, the computation modules (COMPUTE) never import pages, reports or the ui kit.
A mistake in one feature therefore cannot break another feature.
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

SHARED = {"core", "ui", "connect"}
FEATURES = {"weekly", "search_terms", "products", "changes", "onboarding", "ai"}
# component -> components it may import (besides itself).
ALLOWED = {
    "core": set(),
    "ui": {"core"},
    "connect": {"core"},
    "onboarding": {"core"},
    "changes": {"core", "ui"},
    "weekly": {"core", "ui"},
    "search_terms": {"core", "ui"},
    "products": {"core", "ui"},
    "ai": {"core", "ui", "weekly"},
}
# feature -> its computation modules (no pages/reports/ui inside these)
COMPUTE = {"weekly": {"analysis", "findings"}, "search_terms": {"analysis"}, "products": {"analysis"},
           "changes": {"pipeline", "store"}, "onboarding": {"context"}, "ai": {"insights"}}


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


def gads_module_imports(path: Path) -> set[str]:
    """Every gads.<component>.<module> the file imports."""
    out = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("gads."):
            out.add(node.module)
        elif isinstance(node, ast.Import):
            out.update(a.name for a in node.names if a.name.startswith("gads."))
    return out


class BoundaryTest(unittest.TestCase):
    def test_every_module_belongs_to_a_component(self):
        loose = [p.name for p in GADS.glob("*.py") if p.name != "__init__.py"]
        self.assertEqual(loose, [], "put new modules inside a component package")
        self.assertEqual(sorted(p.name for p in GADS.iterdir() if p.is_dir() and p.name != "__pycache__"),
                         sorted(ALLOWED))

    def test_components_only_import_allowed_components(self):
        violations = []
        for component, allowed in ALLOWED.items():
            for path in (GADS / component).rglob("*.py"):
                for target, line in gads_imports(path):
                    if target != component and target not in allowed:
                        violations.append(f"{path.relative_to(ROOT)}:{line} imports gads.{target}")
        self.assertEqual(violations, [])

    def test_features_are_independent_and_shared_layers_never_import_features(self):
        self.assertEqual(SHARED | FEATURES, set(ALLOWED))
        for component in SHARED:
            self.assertFalse(ALLOWED[component] & FEATURES, component)
        for feature in FEATURES - {"ai"}:
            self.assertFalse(ALLOWED[feature] & FEATURES, feature)

    def test_computation_never_imports_pages_reports_or_ui(self):
        bad = []
        for feature, compute in COMPUTE.items():
            for name in compute:
                path = GADS / feature / f"{name}.py"
                self.assertTrue(path.exists(), path)
                for mod in gads_module_imports(path):
                    parts = mod.split(".")
                    if parts[1] == "ui" or (parts[1] == feature and len(parts) > 2 and parts[2] not in compute):
                        bad.append(f"{path.relative_to(ROOT)} imports {mod}")
        self.assertEqual(bad, [])

    def test_no_relative_imports(self):
        # relative imports ("from ..present import x") would slip past the component check; use gads.<component>
        bad = [f"{p.relative_to(ROOT)}:{n.lineno}" for p in GADS.rglob("*.py")
               for n in ast.walk(ast.parse(p.read_text())) if isinstance(n, ast.ImportFrom) and n.level]
        self.assertEqual(bad, [])

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
        names = [n.module or "" for n in top if isinstance(n, ast.ImportFrom)]
        names += [a.name for n in top if isinstance(n, ast.Import) for a in n.names]
        self.assertFalse([m for m in names if m == "gads.ai" or m.startswith("gads.ai.")])


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
    base = GADS / component
    return [".".join(("gads", component, *p.relative_to(base).with_suffix("").parts))
            for p in base.rglob("*.py") if p.stem != "__init__"]


class IndependenceTest(unittest.TestCase):
    """Each component imports with every component it does not depend on made unimportable."""

    def test_each_component_works_without_the_others(self):
        for component, allowed in ALLOWED.items():
            blocked = [f"gads.{c}" for c in ALLOWED if c != component and c not in allowed]
            r = import_with_blocked(blocked, modules_of(component))
            self.assertEqual(r.returncode, 0, f"{component} needs a component it should not:\n{r.stderr[-800:]}")

    def test_weekly_analysis_runs_without_pages_ui_ai_or_other_features(self):
        args = ["--snapshot", str(ROOT / "tests" / "fixtures" / "synthetic_weekly_two_weeks.json"),
                "--current", "2026-10-13:2026-10-19", "--previous", "2026-10-06:2026-10-12",
                "--now", "2026-10-25T09:00:00+00:00"]
        blocked = ["gads.ui", "gads.ai", "gads.weekly.report", "gads.weekly.dashboard", "gads.search_terms",
                   "gads.products", "gads.changes", "gads.onboarding", "gads.connect"]
        code = BLOCKER.format(blocked=blocked, scripts=str(SCRIPTS)) + f"""
import argparse
from gads.weekly.analysis import build_review
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


class ChangeRequestIsolationTest(unittest.TestCase):
    def test_propose_and_list_work_without_the_status_page_or_other_features(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocked = ["gads.changes.page", "gads.ui", "gads.ai", "gads.weekly", "gads.search_terms", "gads.products"]
            code = BLOCKER.format(blocked=blocked, scripts=str(SCRIPTS)) + f"""
import change_requests
common = ["--requests-dir", {tmp!r} + "/req", "--change-log", {tmp!r} + "/log.md", "--config", {tmp!r} + "/x.json"]
assert change_requests.main(["propose", "--operation", "pause_campaign", "--customer-id", "900-000-0000",
                             "--param", "campaign_id=9000000001", "--rationale", "SYNTHETIC", "--evidence", "e",
                             *common]) == 0
assert change_requests.main(["list", *common]) == 0
"""
            r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr[-800:])
            self.assertIn("pause_campaign", r.stdout)


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
            self.assertEqual(code, 3)  # finished, with an optional part skipped
            self.assertIn("AI analysis is unavailable", html)
            self.assertIn("273.00 EUR", html)  # the engine's numbers are still there
            self.assertFalse((out / "facts.json").exists())
        self.assertIn("AI analysis skipped", err.getvalue())
        self.assertIn("Traceback (most recent call last)", err.getvalue())
        self.assertIn("1 optional part skipped", err.getvalue())

    def test_invalid_insights_file_only_replaces_the_insights_section(self):
        import dashboard
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "insights.json"
            bad.write_text("{not json")
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
                code = dashboard.main(self.WEEKLY + ["--insights", str(bad), "--out", tmp + "/o"])
            out = next(Path(tmp, "o").iterdir())
            html = (out / "index.html").read_text()
            self.assertEqual(code, 3)
            self.assertIn("insights file could not be used", html)
            self.assertIn('id="ask"', html)                  # the Ask box still works
            self.assertTrue((out / "facts.json").exists())   # and has its facts
            self.assertIn("AI insights skipped", err.getvalue())

    def test_missing_insights_file_stops_before_writing(self):
        import dashboard
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
                code = dashboard.main(self.WEEKLY + ["--insights", tmp + "/nope.json", "--out", tmp + "/o"])
            self.assertEqual(code, 2)
            self.assertIn("--insights file not found", err.getvalue())
            self.assertFalse(Path(tmp, "o").exists())

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
                self.assertEqual(code, 3)
                self.assertTrue((out / data_file).exists())
                self.assertTrue((out / "review.md").exists())
                self.assertFalse((out / "dashboard.html").exists())
                self.assertIn("(dashboard page) skipped", err.getvalue())
                self.assertIn("RuntimeError: synthetic page bug", err.getvalue())  # full traceback, not just a line
                self.assertIn("Traceback (most recent call last)", err.getvalue())
                json.loads((out / data_file).read_text())


class GuardBehaviourTest(unittest.TestCase):
    """The optional-part guard: traceback shown, exit 3, strict mode, disk errors not swallowed."""

    def setUp(self):
        from gads.core import cli
        self.cli = cli
        cli.SKIPPED.clear()

    def test_clean_run_exits_0_and_skipped_run_exits_3(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.cli.run_cli(lambda a: "out", None), 0)

            def degraded(_):
                self.cli.guarded("demo part", lambda: 1 / 0)
                return "out"
            self.assertEqual(self.cli.run_cli(degraded, None), 3)

    def test_strict_mode_raises_instead_of_skipping(self):
        with mock.patch.dict("os.environ", {"GADS_STRICT": "1"}), self.assertRaises(ZeroDivisionError):
            self.cli.guarded("demo part", lambda: 1 / 0)
        self.assertEqual(self.cli.SKIPPED, [])

    def test_disk_errors_are_not_swallowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "missing-dir" / "page.html"  # parent does not exist -> OSError on write
            with self.assertRaises(OSError):
                self.cli.write_optional(target, lambda: "<html>", "dashboard page")
        with self.assertRaises(OSError):
            self.cli.guarded("demo part", lambda: open("/nonexistent/x"))


if __name__ == "__main__":
    unittest.main()
