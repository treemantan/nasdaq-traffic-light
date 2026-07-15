from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from market_report.config import load_config


class CoreEtfPlanConfigTests(unittest.TestCase):
    def test_private_environment_json_overrides_public_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps({"core_etf_plan": {"enabled": False}}),
                encoding="utf-8",
            )
            private_plan = {
                "enabled": True,
                "allocations": [{"symbol": "VUAG.L", "planned_addition_gbp": 5000}],
            }

            with patch.dict(
                "os.environ",
                {"CORE_ETF_PLAN_JSON": json.dumps(private_plan)},
                clear=False,
            ):
                config = load_config(str(path))

        self.assertEqual(config.core_etf_plan, private_plan)

    def test_environment_value_must_be_json_object(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text("{}", encoding="utf-8")

            with patch.dict("os.environ", {"CORE_ETF_PLAN_JSON": "[]"}, clear=False):
                with self.assertRaisesRegex(ValueError, "JSON object"):
                    load_config(str(path))


if __name__ == "__main__":
    unittest.main()
