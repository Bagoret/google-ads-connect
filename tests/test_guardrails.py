"""Guardrails: the query library is read-only and fully mapped; settings deny writes."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUERIES = ROOT / "queries"


def selected_fields(gaql: str) -> list[str]:
    """Return the field paths between SELECT and FROM."""
    match = re.search(r"SELECT(.*?)FROM", gaql, re.S | re.I)
    if not match:
        return []
    return [f.strip() for f in match.group(1).split(",") if f.strip()]


class QueryLibraryTest(unittest.TestCase):
    def queries(self):
        files = sorted(QUERIES.glob("*.gaql"))
        self.assertTrue(files, "no .gaql files found")
        return files

    def test_expected_queries_exist(self):
        names = {q.stem for q in self.queries()}
        expected = {
            "customer_settings", "campaign_inventory", "campaign_daily",
            "conversion_actions", "keywords", "negative_keywords",
            "search_terms", "product_daily",
        }
        self.assertTrue(expected <= names, expected - names)

    def test_every_query_is_read_only_select(self):
        for q in self.queries():
            text = q.read_text().upper()
            self.assertTrue(text.lstrip().startswith("SELECT"), q.name)
            for word in ("MUTATE", "CREATE", "UPDATE", "REMOVE", "INSERT", "DELETE"):
                self.assertNotRegex(text, rf"\b{word}\b", (q.name, word))

    def test_only_known_placeholders(self):
        for q in self.queries():
            found = set(re.findall(r"\{(\w+)\}", q.read_text()))
            self.assertLessEqual(found, {"start", "end"}, q.name)

    def test_field_map_covers_every_selected_field(self):
        fmap = json.loads((ROOT / "config" / "field_map.json").read_text())
        for q in self.queries():
            for field in selected_fields(q.read_text()):
                self.assertIn(field, fmap, (q.name, field))

    def test_field_map_types_are_known(self):
        fmap = json.loads((ROOT / "config" / "field_map.json").read_text())
        allowed = {"id", "str", "int", "decimal", "micros", "date"}
        for path, spec in fmap.items():
            self.assertIn(spec["type"], allowed, path)
            self.assertTrue(spec["name"], path)


class SettingsTest(unittest.TestCase):
    def test_settings_deny_gomarble_and_raw_edits(self):
        deny = json.loads((ROOT / ".claude" / "settings.json").read_text())["permissions"]["deny"]
        self.assertIn("mcp__GoMarble_AI", deny)
        self.assertIn("Edit(data/raw/**)", deny)
        self.assertIn("Write(data/raw/**)", deny)

    def test_mcp_example_has_placeholders_only(self):
        cfg = json.loads((ROOT / ".mcp.json.example").read_text())
        server = cfg["mcpServers"]["google-ads-mcp"]
        self.assertEqual(server["command"], "pipx")
        for value in server.get("env", {}).values():
            self.assertTrue(value.startswith("YOUR_") or value.startswith("PATH_TO_"), value)


if __name__ == "__main__":
    unittest.main()
