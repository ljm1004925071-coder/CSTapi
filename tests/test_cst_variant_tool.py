import unittest
from pathlib import Path

from cst_variant_tool import (
    build_variants_from_config,
    build_history_manifest,
    build_parameter_csv_rows,
    create_variant_config_from_parameter_csv,
    create_variant_config_template,
    detect_command_text,
    export_history_manifest,
    export_parameter_edit_table,
    get_parameter_store_target,
    import_parameter_table_and_build,
    open_project,
    normalize_manifest,
    read_project_parameters_from_path,
    render_variant_items,
    update_manifest_from_parameter_csv,
    validate_variant_config,
)


class VariantToolTests(unittest.TestCase):
    def setUp(self):
        self.parameterized_history_payload = {
            "list": [
                {
                    "name": "create_patch",
                    "text": (
                        "With Brick\n"
                        "    .Reset\n"
                        "    .Name \"patch\"\n"
                        "    .Xrange \"-w_patch/2\", \"w_patch/2\"\n"
                        "    .Yrange \"-l_patch/2\", \"l_patch/2\"\n"
                        "    .Zrange \"0\", \"t_cu\"\n"
                        "    .Create\n"
                        "End With\n"
                    ),
                    "hide": False,
                }
            ]
        }
        self.project_parameters = [
            {"name": "w_patch", "value": "5.0", "string_value": "5.0", "numeric_value": 5.0},
            {"name": "l_patch", "value": "4.0", "string_value": "4.0", "numeric_value": 4.0},
            {"name": "t_cu", "value": "0.035", "string_value": "0.035", "numeric_value": 0.035},
            {"name": "unused_param", "value": "10", "string_value": "10", "numeric_value": 10.0},
        ]
        self.parameter_manifest = build_history_manifest(
            project_path=Path("D:/models/template.cst"),
            history_payload=self.parameterized_history_payload,
            project_parameters=self.project_parameters,
        )
        self.numeric_manifest = build_history_manifest(
            project_path=Path("D:/models/template.cst"),
            history_payload={
                "list": [
                    {
                        "name": "create_patch",
                        "text": 'Brick.Xrange "-2.5", "2.5"\n',
                        "hide": False,
                    }
                ]
            },
        )

    def test_manifest_extracts_referenced_project_parameters(self):
        self.assertEqual(self.parameter_manifest["parameter_source_mode"], "project_parameters")
        self.assertEqual(self.parameter_manifest["parameter_count"], 3)
        parameter_names = [item["parameter_name"] for item in self.parameter_manifest["parameters"]]
        self.assertEqual(parameter_names, ["w_patch", "l_patch", "t_cu"])
        self.assertNotIn("unused_param", parameter_names)
        self.assertEqual(self.parameter_manifest["items"][0]["candidates"][0]["parameter_name"], "w_patch")

    def test_detect_command_text_reads_nested_contents_payload(self):
        history_item = {
            "name": "define brick",
            "contents": [
                {"command": ""},
                {
                    "content": [
                        "With Brick",
                        '    .Name "patch"',
                        '    .Xrange "-w_patch/2", "w_patch/2"',
                        "End With",
                    ]
                },
            ],
        }
        command_text, command_key = detect_command_text(history_item)
        self.assertEqual(command_key, "contents")
        self.assertIn("With Brick", command_text)
        self.assertIn('.Xrange "-w_patch/2", "w_patch/2"', command_text)

    def test_validate_variant_config_accepts_enabled_project_parameter_values(self):
        self.parameter_manifest["parameters"][0]["enabled"] = True
        config = {
            "template_project": "D:/models/template.cst",
            "history_manifest": "D:/tmp/history_manifest.json",
            "output_dir": "D:/tmp/out",
            "output_mode": "separate_projects",
            "variants": [{"variant_id": "v1", "values": {"w_patch": "6.5"}}],
        }
        errors = validate_variant_config(config, self.parameter_manifest)
        self.assertEqual(errors, [])

    def test_build_parameter_csv_rows_returns_simple_table(self):
        self.parameter_manifest["parameters"][0]["enabled"] = True
        rows = build_parameter_csv_rows(self.parameter_manifest, variant_ids=["variant_001"])
        self.assertEqual(rows[0]["parameter_name"], "w_patch")
        self.assertEqual(rows[0]["enable"], "true")
        self.assertEqual(rows[0]["initial_value"], "5.0")
        self.assertIn("used in history items", rows[0]["comment"])
        self.assertIn("variant_001", rows[0])

    def test_update_manifest_from_parameter_csv_syncs_enable_and_comment(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "history_manifest.json"
            csv_path = Path(tmpdir) / "history_manifest_parameters.csv"

            json_text = __import__("json").dumps(self.parameter_manifest, indent=2, ensure_ascii=True)
            manifest_path.write_text(json_text, encoding="utf-8")
            csv_path.write_text(
                (
                    "parameter_name,comment,enable,initial_value\n"
                    "w_patch,main width,true,6.5\n"
                    "l_patch,length control,false,4.2\n"
                ),
                encoding="utf-8-sig",
            )

            updated = update_manifest_from_parameter_csv(manifest_path, csv_path)

            by_name = {item["parameter_name"]: item for item in updated["parameters"]}
            self.assertTrue(by_name["w_patch"]["enabled"])
            self.assertEqual(by_name["w_patch"]["comment"], "main width")
            self.assertEqual(by_name["w_patch"]["original_expression"], "6.5")
            self.assertFalse(by_name["l_patch"]["enabled"])
            self.assertEqual(by_name["l_patch"]["comment"], "length control")
            self.assertEqual(by_name["l_patch"]["original_expression"], "4.2")

    def test_render_variant_items_keeps_existing_parameterized_history(self):
        self.parameter_manifest["parameters"][0]["enabled"] = True
        rendered_items, applied_values = render_variant_items(
            self.parameter_manifest, {"w_patch": "6.5"}
        )
        first_text = rendered_items[0]["command_text"]
        self.assertIn("w_patch/2", first_text)
        self.assertEqual(applied_values["param_w_patch"], "6.5")

    def test_numeric_fallback_still_rewrites_enabled_literal_candidates(self):
        self.numeric_manifest["parameters"][0]["enabled"] = True
        rendered_items, applied_values = render_variant_items(
            self.numeric_manifest, {"h0001_v01": -3.25}
        )
        first_text = rendered_items[0]["command_text"]
        self.assertIn("brick_01", first_text)
        self.assertEqual(applied_values["h0001_v01"], "-3.25")

    def test_top_level_parameters_are_canonical(self):
        self.parameter_manifest["parameters"][0]["enabled"] = True
        normalized = normalize_manifest(self.parameter_manifest)
        self.assertTrue(normalized["parameters"][0]["enabled"])
        self.assertNotIn("enabled", normalized["items"][0]["candidates"][0])

    def test_export_history_manifest_can_write_json_without_live_cst(self):
        import tempfile
        from unittest.mock import patch

        history_payload = {
            "list": [{"name": "step_1", "text": 'Brick.Xrange "w_patch", "2"\n', "hide": False}]
        }
        parameters = [
            {"name": "w_patch", "value": "5.0", "string_value": "5.0", "numeric_value": 5.0}
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "history_manifest.json"
            csv_path = Path(tmpdir) / "history_parameters.csv"
            with patch("cst_variant_tool._MODULE.connect_design_environment", return_value=object()), patch(
                "cst_variant_tool._MODULE.open_project", return_value=object()
            ), patch(
                "cst_variant_tool._MODULE.read_project_parameters", return_value=parameters
            ), patch(
                "cst_variant_tool._MODULE.read_history_payload", return_value=history_payload
            ):
                manifest = export_history_manifest(
                    "D:/models/template.cst",
                    output_path,
                    parameter_csv_path=csv_path,
                    connect_to_any=True,
                )

            self.assertTrue(output_path.exists())
            self.assertTrue(csv_path.exists())
            self.assertEqual(manifest["parameter_source_mode"], "project_parameters")
            self.assertEqual(manifest["parameter_count"], 1)

    def test_export_history_manifest_auto_writes_default_csv_next_to_json(self):
        import tempfile
        from unittest.mock import patch

        history_payload = {
            "list": [{"name": "step_1", "text": 'Brick.Xrange "w_patch", "2"\n', "hide": False}]
        }
        parameters = [
            {"name": "w_patch", "value": "5.0", "string_value": "5.0", "numeric_value": 5.0}
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "history_manifest.json"
            default_csv = Path(tmpdir) / "history_manifest_parameters.csv"
            with patch("cst_variant_tool._MODULE.connect_design_environment", return_value=object()), patch(
                "cst_variant_tool._MODULE.open_project", return_value=object()
            ), patch(
                "cst_variant_tool._MODULE.read_project_parameters", return_value=parameters
            ), patch(
                "cst_variant_tool._MODULE.read_history_payload", return_value=history_payload
            ):
                export_history_manifest(
                    "D:/models/template.cst",
                    output_path,
                    connect_to_any=True,
                )

            self.assertTrue(output_path.exists())
            self.assertTrue(default_csv.exists())

    def test_build_variants_from_config_supports_dry_run(self):
        import json
        import tempfile

        manifest = self.parameter_manifest
        for parameter in manifest["parameters"]:
            if parameter["parameter_name"] in {"w_patch", "l_patch"}:
                parameter["enabled"] = True

        config = {
            "template_project": "D:/CSTapi/UNITTEST/TA-theta15.cst",
            "history_manifest": "",
            "output_dir": "",
            "output_mode": "separate_projects",
            "variants": [
                {"variant_id": "v1", "values": {"w_patch": "6.1", "l_patch": "4.7"}}
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "history_manifest.json"
            config_path = Path(tmpdir) / "variant_config.json"
            output_dir = Path(tmpdir) / "out"

            manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
            config["history_manifest"] = str(manifest_path)
            config["output_dir"] = str(output_dir)
            config_path.write_text(json.dumps(config, indent=2, ensure_ascii=True), encoding="utf-8")

            result = build_variants_from_config(
                config_path=config_path,
                dry_run=True,
                dump_rendered_history=True,
            )

            self.assertEqual(result["variants"][0]["status"], "dry_run")
            self.assertTrue((output_dir / "variants_manifest.json").exists())
            self.assertTrue((output_dir / "rendered_history" / "v1.json").exists())

    def test_build_variants_from_config_uses_subprocess_for_project_parameters(self):
        import json
        import tempfile
        from unittest.mock import patch

        manifest = self.parameter_manifest
        for parameter in manifest["parameters"]:
            if parameter["parameter_name"] in {"w_patch", "l_patch"}:
                parameter["enabled"] = True

        config = {
            "template_project": "D:/CSTapi/UNITTEST/TA-theta15.cst",
            "history_manifest": "",
            "output_dir": "",
            "output_mode": "separate_projects",
            "variants": [
                {"variant_id": "v1", "values": {"w_patch": "6.1", "l_patch": "4.7"}}
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "history_manifest.json"
            config_path = Path(tmpdir) / "variant_config.json"
            output_dir = Path(tmpdir) / "out"

            manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
            config["history_manifest"] = str(manifest_path)
            config["output_dir"] = str(output_dir)
            config_path.write_text(json.dumps(config, indent=2, ensure_ascii=True), encoding="utf-8")

            fake_completed = type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            with patch("cst_variant_tool._MODULE.subprocess.run", return_value=fake_completed) as mocked_run:
                result = build_variants_from_config(
                    config_path=config_path,
                    dry_run=False,
                    dump_rendered_history=False,
                )

            self.assertEqual(result["variants"][0]["status"], "success")
            self.assertTrue(mocked_run.called)

    def test_create_variant_config_template_writes_json(self):
        import json
        import tempfile

        manifest = self.parameter_manifest
        manifest["parameters"][0]["enabled"] = True

        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "history_manifest.json"
            config_path = Path(tmpdir) / "variant_config.json"
            manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")

            config = create_variant_config_template(
                manifest_path=manifest_path,
                output_path=config_path,
            )

            self.assertTrue(config_path.exists())
            self.assertEqual(config["variants"][0]["values"]["w_patch"], "5.0")

    def test_create_variant_config_from_parameter_csv_reads_variant_columns(self):
        import json
        import tempfile

        manifest = self.parameter_manifest
        manifest["parameters"][0]["enabled"] = True
        manifest["parameters"][1]["enabled"] = True

        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "history_manifest.json"
            csv_path = Path(tmpdir) / "parameter_table.csv"
            config_path = Path(tmpdir) / "variant_config.json"
            manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
            csv_path.write_text(
                (
                    "parameter_name,comment,enable,initial_value,variant_001,variant_002\n"
                    "w_patch,main width,true,5.0,6.1,6.3\n"
                    "l_patch,main length,true,4.0,4.8,5.0\n"
                    "t_cu,thickness,false,0.035,,\n"
                ),
                encoding="utf-8-sig",
            )

            config = create_variant_config_from_parameter_csv(
                manifest_path=manifest_path,
                parameter_csv_path=csv_path,
                output_path=config_path,
            )

            self.assertTrue(config_path.exists())
            self.assertEqual(len(config["variants"]), 2)
            self.assertEqual(config["variants"][0]["values"]["w_patch"], "6.1")
            self.assertEqual(config["variants"][1]["values"]["l_patch"], "5.0")

    def test_read_project_parameters_from_path_uses_open_project(self):
        from unittest.mock import patch

        fake_parameters = [{"name": "w_patch", "value": "5.0"}]
        with patch("cst_variant_tool._MODULE.connect_design_environment", return_value=object()), patch(
            "cst_variant_tool._MODULE.open_project", return_value=object()
        ), patch(
            "cst_variant_tool._MODULE.read_project_parameters", return_value=fake_parameters
        ):
            result = read_project_parameters_from_path(
                r"D:\CSTapi\UNITTEST\TA-theta15.cst",
                connect_to_any=True,
            )
        self.assertEqual(result, fake_parameters)

    def test_get_parameter_store_target_prefers_project(self):
        from types import SimpleNamespace

        project_target = SimpleNamespace(StoreParameter=lambda *args, **kwargs: None)
        schematic_target = SimpleNamespace(StoreParameter=lambda *args, **kwargs: None)
        project = SimpleNamespace(schematic=schematic_target)
        project.StoreParameter = project_target.StoreParameter

        target = get_parameter_store_target(project)
        self.assertIs(target, project)

    def test_export_parameter_edit_table_writes_manifest_and_csv(self):
        from unittest.mock import patch
        import tempfile

        fake_manifest = {
            "history_item_count": 10,
            "parameter_count": 2,
            "parameters": [],
            "items": [],
            "candidates": [],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("cst_variant_tool._MODULE.export_history_manifest", return_value=fake_manifest), patch(
                "cst_variant_tool._MODULE.write_parameter_csv"
            ):
                result = export_parameter_edit_table(
                    project_path=r"D:\CSTapi\UNITTEST\TA-theta15.cst",
                    work_dir=tmpdir,
                    variant_ids=["variant_001"],
                    connect_to_any=True,
                )
        self.assertIn("manifest_path", result)
        self.assertIn("parameter_csv_path", result)

    def test_import_parameter_table_and_build_runs_end_to_end_helpers(self):
        from unittest.mock import patch
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "history_manifest.json"
            csv_path = Path(tmpdir) / "parameter_table.csv"
            manifest_path.write_text("{}", encoding="utf-8")
            csv_path.write_text("parameter_name,comment,enable,initial_value\n", encoding="utf-8-sig")

            with patch("cst_variant_tool._MODULE.update_manifest_from_parameter_csv", return_value={"ok": 1}), patch(
                "cst_variant_tool._MODULE.create_variant_config_from_parameter_csv", return_value={"variants": []}
            ), patch(
                "cst_variant_tool._MODULE.build_variants_from_config", return_value={"variants": []}
            ):
                result = import_parameter_table_and_build(
                    manifest_path=manifest_path,
                    parameter_csv_path=csv_path,
                    connect_to_any=True,
                )

        self.assertEqual(result["updated_manifest"], {"ok": 1})

    def test_open_project_reuses_already_open_project(self):
        from types import SimpleNamespace

        open_handle = object()

        class FakeDE:
            def list_open_projects(self):
                return [r"D:\models\template.cst"]

            def get_open_project(self, path):
                self.got_path = path
                return open_handle

            def open_project(self, path):
                raise AssertionError("open_project should not be called when project is already open")

        session = SimpleNamespace(design_environment=FakeDE())
        project = open_project(session, Path(r"D:\models\template.cst"))
        self.assertIs(project, open_handle)


if __name__ == "__main__":
    unittest.main()
