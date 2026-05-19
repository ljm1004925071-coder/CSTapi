from pathlib import Path
import importlib.util


_MODULE_PATH = Path(__file__).resolve().parent.parent / "cst_variant_tool.py"
_SPEC = importlib.util.spec_from_file_location("_cst_variant_tool_impl", _MODULE_PATH)

if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Unable to load cst_variant_tool implementation from {_MODULE_PATH}")

_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


export_history_manifest = _MODULE.export_history_manifest
build_variants_from_config = _MODULE.build_variants_from_config
build_history_manifest = _MODULE.build_history_manifest
build_parameter_csv_rows = _MODULE.build_parameter_csv_rows
create_variant_config_template = _MODULE.create_variant_config_template
create_variant_config_from_parameter_csv = _MODULE.create_variant_config_from_parameter_csv
detect_command_text = _MODULE.detect_command_text
export_parameter_edit_table = _MODULE.export_parameter_edit_table
get_parameter_store_target = _MODULE.get_parameter_store_target
import_parameter_table_and_build = _MODULE.import_parameter_table_and_build
normalize_manifest = _MODULE.normalize_manifest
read_project_parameters_from_path = _MODULE.read_project_parameters_from_path
update_manifest_from_parameter_csv = _MODULE.update_manifest_from_parameter_csv
render_variant_items = _MODULE.render_variant_items
validate_variant_config = _MODULE.validate_variant_config
connect_design_environment = _MODULE.connect_design_environment
open_project = _MODULE.open_project
read_history_payload = _MODULE.read_history_payload
read_project_parameters = _MODULE.read_project_parameters


__all__ = [
    "export_history_manifest",
    "build_variants_from_config",
    "build_history_manifest",
    "build_parameter_csv_rows",
    "create_variant_config_from_parameter_csv",
    "create_variant_config_template",
    "detect_command_text",
    "export_parameter_edit_table",
    "get_parameter_store_target",
    "import_parameter_table_and_build",
    "normalize_manifest",
    "read_project_parameters_from_path",
    "update_manifest_from_parameter_csv",
    "render_variant_items",
    "validate_variant_config",
    "connect_design_environment",
    "open_project",
    "read_history_payload",
    "read_project_parameters",
]
