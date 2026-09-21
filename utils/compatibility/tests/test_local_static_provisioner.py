from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import yaml


COMPATIBILITY_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = COMPATIBILITY_DIR / "scrapers" / "local-static-provisioner.py"
sys.path.insert(0, str(COMPATIBILITY_DIR))

spec = importlib.util.spec_from_file_location("local_static_provisioner", MODULE_PATH)
local_static_provisioner = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(local_static_provisioner)


MATRIX = b"""
# Local Static Provisioner

## Version Compatibility

| Provisioner Version | K8s Version |
|---------------------|-------------|
| [2.9.0][9]          | 1.21+       |
| [2.8.0][8]          | 1.21+       |
| [2.7.0][7]          | 1.21+       |

## Feature Status
| Not | The target table |
| 9.9.9 | 1.10+ |
"""


class LocalStaticProvisionerScraperTest(unittest.TestCase):
    def test_parse_compatibility_matrix_reads_only_target_section(self):
        rows = local_static_provisioner.parse_compatibility_matrix(MATRIX, "1.24")

        self.assertEqual(list(rows), ["2.9.0", "2.8.0", "2.7.0"])
        self.assertEqual(rows["2.9.0"], ["1.21", "1.22", "1.23", "1.24"])
        self.assertNotIn("9.9.9", rows)

    def test_parse_compatibility_matrix_rejects_unsupported_kube_notation(self):
        content = MATRIX.replace(b"1.21+", b"1.21 - 1.24")
        with patch.object(local_static_provisioner, "print_error"):
            rows = local_static_provisioner.parse_compatibility_matrix(
                content, "1.24"
            )

        self.assertEqual(rows, {})

    def test_parse_compatibility_matrix_rejects_future_minimum(self):
        content = MATRIX.replace(b"1.21+", b"1.37+")
        with patch.object(local_static_provisioner, "print_error"):
            rows = local_static_provisioner.parse_compatibility_matrix(
                content, "1.36"
            )

        self.assertEqual(rows, {})

    def test_build_rows_keeps_documented_release_without_exact_chart(self):
        rows = local_static_provisioner.build_rows(
            {
                "2.9.0": ["1.21", "1.22"],
                "2.8.0": ["1.21", "1.22"],
                "2.7.0": ["1.21", "1.22"],
            },
            {"2.9.0": "2.9.0", "2.8.0": "2.8.0"},
        )

        self.assertEqual(rows[0]["chart_version"], "2.9.0")
        self.assertEqual(rows[1]["chart_version"], "2.8.0")
        self.assertNotIn("chart_version", rows[2])

    def test_scrape_writes_documented_rows_and_exact_chart_matches(self):
        with patch.object(
            local_static_provisioner, "fetch_page", return_value=MATRIX
        ), patch.object(
            local_static_provisioner, "current_kube_version", return_value="1.23"
        ), patch.object(
            local_static_provisioner,
            "get_chart_versions",
            return_value={"2.9.0": "2.9.0", "2.8.0": "2.8.0"},
        ), patch.object(
            local_static_provisioner, "update_compatibility_info"
        ) as update:
            local_static_provisioner.scrape()

        update.assert_called_once()
        rows = update.call_args.args[1]
        self.assertEqual([row["version"] for row in rows], ["2.9.0", "2.8.0", "2.7.0"])
        self.assertEqual(rows[0]["kube"], ["1.21", "1.22", "1.23"])
        self.assertNotIn("chart_version", rows[2])

    def test_scrape_fails_closed_when_matrix_is_missing(self):
        with patch.object(
            local_static_provisioner, "fetch_page", return_value=b"# no matrix"
        ), patch.object(
            local_static_provisioner, "current_kube_version", return_value="1.23"
        ), patch.object(
            local_static_provisioner, "print_error"
        ), patch.object(
            local_static_provisioner, "update_compatibility_info"
        ) as update:
            local_static_provisioner.scrape()

        update.assert_not_called()

    def test_scrape_fails_closed_when_chart_index_is_unavailable(self):
        with patch.object(
            local_static_provisioner, "fetch_page", return_value=MATRIX
        ), patch.object(
            local_static_provisioner, "current_kube_version", return_value="1.23"
        ), patch.object(
            local_static_provisioner, "get_chart_versions", return_value={}
        ), patch.object(
            local_static_provisioner, "print_error"
        ), patch.object(
            local_static_provisioner, "update_compatibility_info"
        ) as update:
            local_static_provisioner.scrape()

        update.assert_not_called()

    def test_checked_in_table_matches_documented_rows_and_aggregate(self):
        root = COMPATIBILITY_DIR.parents[1]
        addon = yaml.safe_load(
            (root / "static/compatibilities/local-static-provisioner.yaml").read_text()
        )
        versions = {row["version"]: row for row in addon["versions"]}
        matrix = local_static_provisioner.parse_compatibility_matrix(MATRIX, "1.36")

        self.assertEqual(set(versions), set(matrix))
        for version, kube_versions in matrix.items():
            self.assertEqual(versions[version]["kube"], list(reversed(kube_versions)))
        self.assertEqual(versions["2.9.0"]["chart_version"], "2.9.0")
        self.assertEqual(versions["2.8.0"]["chart_version"], "2.8.0")
        self.assertNotIn("chart_version", versions["2.7.0"])

        aggregate = yaml.safe_load((root / "static/compatibilities.yaml").read_text())
        aggregate_row = next(
            row
            for row in aggregate["addons"]
            if row["name"] == "local-static-provisioner"
        )
        self.assertEqual(aggregate_row, {**addon, "name": "local-static-provisioner"})


if __name__ == "__main__":
    unittest.main()
