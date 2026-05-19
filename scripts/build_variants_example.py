import sys

sys.path.append(r"D:\CSTapi")

from cst_variant_tool import build_variants_from_config


VARIANT_CONFIG_PATH = r"D:\CSTapi\UNITTEST\variant_config.json"


def main() -> None:
    variants_manifest = build_variants_from_config(
        config_path=VARIANT_CONFIG_PATH,
        connect_to_any=True,
        options=["-m", "-i"],
        dry_run=False,
        dump_rendered_history=True,
    )

    print("build variants done")
    print(variants_manifest["output_dir"])


if __name__ == "__main__":
    main()
