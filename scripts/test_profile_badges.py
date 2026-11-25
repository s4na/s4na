import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from unittest.mock import patch

from profile_badges import badge, collect, staleness


NOW = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)


class ProfileBadgeTest(unittest.TestCase):
    def test_only_stale_issues_and_inclusive_boundary(self):
        issues = [{"updated_at": "2026-10-26T12:00:00Z"},
                  {"updated_at": "2026-09-01T12:00:00Z"},
                  {"updated_at": "2026-10-26T12:00:01Z"},
                  {"updated_at": "2026-09-01T12:00:00Z", "pull_request": {}}]
        self.assertEqual(staleness(issues, "issues", NOW, 30), (2, 85))

    def test_excludes_drafts_and_dependabot(self):
        old = {"updated_at": "2026-11-11T12:00:00Z"}
        pulls = [dict(old, draft=False, user={"login": "person"}),
                 dict(old, draft=True, user={"login": "person"}),
                 dict(old, draft=False, user={"login": "dependabot[bot]"})]
        self.assertEqual(staleness(pulls, "pulls", NOW, 14), (1, 14))

    @patch("profile_badges.get", return_value={"private": True})
    def test_never_loads_private_items(self, get):
        result = collect(["s4na/private"], None, NOW)
        get.assert_called_once_with("repos/s4na/private", None)
        self.assertEqual(set(result), {"private-issues.svg", "private-prs.svg"})
        self.assertTrue(all("N/A" in svg for svg in result.values()))

    def test_svg_escapes_attributes(self):
        node = ET.fromstring(badge('x<', '"&', "#123456"))
        self.assertEqual(node.attrib["aria-label"], 'x<: "&')

    @patch("profile_badges.get")
    def test_pagination_counts_all_open_items(self, get):
        opened = {"updated_at": "2026-10-26T12:00:00Z"}
        get.side_effect = [{"private": False, "has_issues": True}, [opened] * 100, [opened], []]
        result = collect(["s4na/public"], None, NOW)
        self.assertIn("101 · max 30d", result["public-issues.svg"])
        self.assertEqual(get.call_count, 4)


if __name__ == "__main__":
    unittest.main()
