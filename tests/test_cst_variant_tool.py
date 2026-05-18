import unittest

from cst_variant_tool import (
    build_history_manifest,
    render_variant_items,
    validate_variant_config,
)


class VariantToolTests(unittest.TestCase):
    def setUp(self):
        history_payload = {
            "list": [
                {
                    "name": "create_patch",
                    "text": (
                        "With Brick\n"
                        "    .Reset\n"
                        "    .Name \"patch\"\n"
                        "    .Xrange \"-2.5\", \"2.5\"\n"
                        "    .Yrange \"-2.0\", \"2.0\"\n"
                        "    .Zrange \"0\", \"0.035\"\n"
                        "    .Create\n"
                        "End With\n"
                    ),
                    "hide": False,
                },
                {"name": "solver", "text": "ChangeSolverType \"HF Frequency Domain\"\n"},
            ]
        }
        self.manifest = build_history_manifest(
            project_path=__import__("pathlib").Path("D:/models/template.cst"),
            history_payload=history_payload,
        )

    def test_manifest_extracts_candidates(self):
        self.assertEqual(self.manifest["history_item_count"], 2)
        self.assertGreaterEqual(self.manifest["candidate_count"], 6)
        first = self.manifest["items"][0]
        self.assertEqual(first["feature_type"], "Brick")
        self.assertEqual(first["candidates"][0]["candidate_id"], "h0001_v01")

    def test_validate_variant_config_requires_enabled_candidates(self):
        config = {
            "template_project": "D:/models/template.cst",
            "history_manifest": "D:/tmp/history_manifest.json",
            "output_dir": "D:/tmp/out",
            "output_mode": "separate_projects",
            "variants": [{"variant_id": "v1", "values": {"h0001_v01": 1.0}}],
        }
        errors = validate_variant_config(config, self.manifest)
        self.assertIn("No enabled candidates were found", errors[0])

    def test_render_variant_items_rewrites_only_enabled_candidates(self):
        self.manifest["candidates"][0]["enabled"] = True
        self.manifest["items"][0]["candidates"][0]["enabled"] = True
        rendered_items, applied_values = render_variant_items(
            self.manifest, {"h0001_v01": -3.25}
        )
        first_text = rendered_items[0]["command_text"]
        self.assertIn('"-3.25"', first_text)
        self.assertIn('"2.5"', first_text)
        self.assertEqual(applied_values["h0001_v01"], -3.25)


if __name__ == "__main__":
    unittest.main()
