import sys

sys.path.append(r"D:\CSTapi")

from cst_variant_tool import export_parameter_edit_table, import_parameter_table_and_build


PROJECT_PATH = r"D:\CSTapi\UNITTEST\TA-theta15.cst"
WORK_DIR = r"D:\CSTapi\UNITTEST\workflow"
MANIFEST_PATH = r"D:\CSTapi\UNITTEST\workflow\history_manifest.json"
CSV_PATH = r"D:\CSTapi\UNITTEST\workflow\parameter_table.csv"


def export_step() -> None:
    result = export_parameter_edit_table(
        project_path=PROJECT_PATH,
        work_dir=WORK_DIR,
        table_name="parameter_table.csv",
        manifest_name="history_manifest.json",
        variant_ids=["variant_001", "variant_002", "variant_003"],
        connect_to_any=True,
        options=["-m", "-i"],
    )
    print("export done")
    print(result["manifest_path"])
    print(result["parameter_csv_path"])


def build_step() -> None:
    result = import_parameter_table_and_build(
        manifest_path=MANIFEST_PATH,
        parameter_csv_path=CSV_PATH,
        connect_to_any=True,
        options=["-m", "-i"],
        dry_run=False,
        dump_rendered_history=True,
    )
    print("build done")
    print(result["variant_config_path"])
    print(result["variants_manifest"]["output_dir"])


if __name__ == "__main__":
    export_step()
    # Edit parameter_table.csv manually, then run build_step() in a second pass.
