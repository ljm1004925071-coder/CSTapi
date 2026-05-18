import argparse
import json
import re
import sys
import traceback
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


NUMERIC_TOKEN_RE = re.compile(
    r'"(?P<quoted>-?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?)"|'
    r"(?<![A-Za-z0-9_])(?P<bare>-?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?)(?![A-Za-z_])"
)


def log(message: str) -> None:
    print(f"[CST-VARIANT] {message}", flush=True)


def sanitize_name(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    text = text.strip("._-")
    return text or "variant"


def slugify(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", value.strip().lower())
    text = text.strip("_")
    return text or "item"


def json_dump(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=True), encoding="utf-8")


def json_load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def path_to_str(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/")


def try_float(value: Any) -> Optional[float]:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def detect_feature_type(command_text: str) -> Optional[str]:
    patterns = [
        re.compile(r"^\s*With\s+([A-Za-z0-9_]+)", re.MULTILINE),
        re.compile(r"^\s*([A-Za-z0-9_]+)\.", re.MULTILINE),
        re.compile(r"^\s*([A-Za-z0-9_]+)\s+\"", re.MULTILINE),
    ]
    for pattern in patterns:
        match = pattern.search(command_text or "")
        if match:
            return match.group(1)
    return None


def detect_command_text(history_item: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    for key in ("code", "text", "content", "command", "vba", "body"):
        value = history_item.get(key)
        if isinstance(value, str) and value.strip():
            return value, key
    return "", None


def detect_history_name(history_item: Dict[str, Any], fallback_index: int) -> str:
    for key in ("name", "title", "caption", "label"):
        value = history_item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"history_item_{fallback_index:04d}"


def compute_line_column(command_text: str, start: int) -> Tuple[int, int]:
    prefix = command_text[:start]
    line = prefix.count("\n") + 1
    column = len(prefix.rsplit("\n", 1)[-1]) + 1
    return line, column


def extract_candidates(
    history_index: int,
    history_name: str,
    feature_type: Optional[str],
    command_text: str,
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    base_name = slugify(feature_type or history_name)

    for ordinal, match in enumerate(NUMERIC_TOKEN_RE.finditer(command_text), start=1):
        raw_value = match.group(0)
        numeric_text = match.group("quoted") or match.group("bare")
        numeric_value = try_float(numeric_text)
        if numeric_value is None:
            continue

        line, column = compute_line_column(command_text, match.start())
        candidate_id = f"h{history_index:04d}_v{ordinal:02d}"
        suggested_label = f"{base_name}_{ordinal:02d}"
        candidates.append(
            {
                "candidate_id": candidate_id,
                "history_index": history_index,
                "ordinal": ordinal,
                "feature_type": feature_type,
                "history_name": history_name,
                "suggested_label": suggested_label,
                "enabled": False,
                "raw_value": raw_value,
                "numeric_text": numeric_text,
                "original_value": numeric_value,
                "span": {"start": match.start(), "end": match.end()},
                "line": line,
                "column": column,
            }
        )
    return candidates


def build_history_manifest(project_path: Path, history_payload: Dict[str, Any]) -> Dict[str, Any]:
    history_list = history_payload.get("list") or []
    manifest_items: List[Dict[str, Any]] = []
    flat_candidates: List[Dict[str, Any]] = []

    for index, raw_item in enumerate(history_list, start=1):
        history_name = detect_history_name(raw_item, index)
        command_text, command_key = detect_command_text(raw_item)
        feature_type = detect_feature_type(command_text)
        candidates = extract_candidates(index, history_name, feature_type, command_text)
        hidden = bool(raw_item.get("hide"))

        item_entry = {
            "history_index": index,
            "name": history_name,
            "hidden": hidden,
            "feature_type": feature_type,
            "command_key": command_key,
            "command_text": command_text,
            "candidate_count": len(candidates),
            "candidates": candidates,
            "raw_item_keys": sorted(raw_item.keys()),
        }
        manifest_items.append(item_entry)
        flat_candidates.extend(deepcopy(candidate) for candidate in candidates)

    return {
        "schema_version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "template_project": path_to_str(project_path),
        "history_item_count": len(manifest_items),
        "candidate_count": len(flat_candidates),
        "items": manifest_items,
        "candidates": flat_candidates,
    }


def build_candidate_lookup(manifest: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    lookup: Dict[str, Dict[str, Any]] = {}
    for candidate in manifest.get("candidates", []):
        for key in (candidate["candidate_id"], candidate.get("suggested_label")):
            if not key:
                continue
            lookup[key] = candidate
    return lookup


def validate_variant_config(config: Dict[str, Any], manifest: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if config.get("output_mode", "separate_projects") != "separate_projects":
        errors.append("Only output_mode='separate_projects' is supported in v1.")

    enabled_candidates = {
        candidate["candidate_id"]: candidate
        for candidate in manifest.get("candidates", [])
        if candidate.get("enabled")
    }
    label_map = {
        candidate.get("suggested_label"): candidate
        for candidate in enabled_candidates.values()
        if candidate.get("suggested_label")
    }

    if not enabled_candidates:
        errors.append("No enabled candidates were found in the history manifest.")

    variants = config.get("variants")
    if not isinstance(variants, list) or not variants:
        errors.append("The config must contain a non-empty 'variants' list.")
        return errors

    seen_ids = set()
    for variant in variants:
        variant_id = variant.get("variant_id")
        if not isinstance(variant_id, str) or not variant_id.strip():
            errors.append("Each variant must define a non-empty string 'variant_id'.")
            continue
        if variant_id in seen_ids:
            errors.append(f"Duplicate variant_id detected: {variant_id}")
        seen_ids.add(variant_id)

        values = variant.get("values")
        if not isinstance(values, dict) or not values:
            errors.append(f"Variant '{variant_id}' must define a non-empty 'values' object.")
            continue

        for key, value in values.items():
            candidate = enabled_candidates.get(key) or label_map.get(key)
            if candidate is None:
                errors.append(
                    f"Variant '{variant_id}' references unknown or disabled candidate '{key}'."
                )
                continue
            if try_float(value) is None:
                errors.append(
                    f"Variant '{variant_id}' value for '{key}' must be numeric, got: {value!r}"
                )
    return errors


def render_variant_items(
    manifest: Dict[str, Any], variant_values: Dict[str, Any]
) -> Tuple[List[Dict[str, Any]], Dict[str, float]]:
    alias_lookup = build_candidate_lookup(manifest)
    applied_values: Dict[str, float] = {}
    by_history_index: Dict[int, List[Dict[str, Any]]] = {}

    for alias, raw_value in variant_values.items():
        candidate = alias_lookup.get(alias)
        if candidate is None or not candidate.get("enabled"):
            continue
        value = try_float(raw_value)
        if value is None:
            continue
        history_index = int(candidate["history_index"])
        by_history_index.setdefault(history_index, []).append(
            {"candidate": candidate, "value": value}
        )
        applied_values[candidate["candidate_id"]] = value

    rendered_items: List[Dict[str, Any]] = []

    for item in manifest.get("items", []):
        history_index = int(item["history_index"])
        replacements = by_history_index.get(history_index, [])
        command_text = item.get("command_text", "")
        rendered_text = command_text

        if replacements and command_text:
            replacements.sort(
                key=lambda entry: int(entry["candidate"]["span"]["start"]), reverse=True
            )
            for replacement in replacements:
                candidate = replacement["candidate"]
                start = int(candidate["span"]["start"])
                end = int(candidate["span"]["end"])
                raw_original = candidate["raw_value"]
                if raw_original.startswith('"') and raw_original.endswith('"'):
                    new_token = f'"{replacement["value"]}"'
                else:
                    new_token = format(replacement["value"], ".15g")
                rendered_text = rendered_text[:start] + new_token + rendered_text[end:]

        rendered_items.append(
            {
                "history_index": history_index,
                "name": item["name"],
                "hidden": item.get("hidden", False),
                "feature_type": item.get("feature_type"),
                "command_text": rendered_text,
            }
        )

    return rendered_items, applied_values


def prepare_output_dir(base_output_dir: Path) -> Path:
    if not base_output_dir.exists():
        base_output_dir.mkdir(parents=True, exist_ok=True)
        return base_output_dir

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = base_output_dir.parent / f"{base_output_dir.name}_{stamp}"
    counter = 1
    while candidate.exists():
        candidate = base_output_dir.parent / f"{base_output_dir.name}_{stamp}_{counter:02d}"
        counter += 1
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


@dataclass
class CSTSession:
    design_environment: Any


def import_cst_interface():
    from cst.interface import DesignEnvironment, running_design_environments

    return DesignEnvironment, running_design_environments


def connect_design_environment(connect_to_any: bool, options: Optional[List[str]]) -> CSTSession:
    DesignEnvironment, _ = import_cst_interface()
    if connect_to_any:
        de = DesignEnvironment.connect_to_any_or_new()
    else:
        de = DesignEnvironment.new(options=options or None)
    return CSTSession(design_environment=de)


def open_project(session: CSTSession, project_path: Path) -> Any:
    return session.design_environment.open_project(str(project_path))


def read_history_payload(project: Any) -> Dict[str, Any]:
    history = project.model3d._GetHistory()
    if not isinstance(history, dict):
        raise RuntimeError("CST returned an unexpected history payload type.")
    return history


def rebuild_project_from_history(
    session: CSTSession, rendered_items: List[Dict[str, Any]], output_path: Path
) -> None:
    project = session.design_environment.new_mws()
    model3d = project.model3d

    for item in rendered_items:
        command_text = item.get("command_text") or ""
        if not command_text.strip():
            continue
        model3d.add_to_history(item["name"], command_text)

    model3d.full_history_rebuild()
    project.save(str(output_path), include_results=False)


def cmd_info(_: argparse.Namespace) -> int:
    _, running_design_environments = import_cst_interface()
    pids = list(running_design_environments())
    log(f"Running design environments: {pids}")
    return 0


def cmd_connect(args: argparse.Namespace) -> int:
    log("Connecting to CST design environment")
    session = connect_design_environment(args.connect_to_any, args.options)
    de = session.design_environment
    log(f"Connected: {type(de).__name__}")
    log(f"Open projects: {de.list_open_projects()}")
    return 0


def cmd_new_mws(args: argparse.Namespace) -> int:
    log("Creating or connecting to design environment")
    session = connect_design_environment(args.connect_to_any, args.options)
    project = session.design_environment.new_mws()
    log(f"Project created: {type(project).__name__}")
    if args.save_as:
        save_path = Path(args.save_as).resolve()
        save_path.parent.mkdir(parents=True, exist_ok=True)
        log(f"Saving project: {save_path}")
        project.save(str(save_path), include_results=False)
    return 0


def cmd_inspect_history(args: argparse.Namespace) -> int:
    project_path = Path(args.project).resolve()
    output_path = Path(args.output).resolve()
    log(f"Inspecting history from: {project_path}")

    session = connect_design_environment(args.connect_to_any, args.options)
    project = open_project(session, project_path)
    history_payload = read_history_payload(project)
    manifest = build_history_manifest(project_path, history_payload)
    json_dump(manifest, output_path)

    log(
        f"History manifest written: {output_path} "
        f"({manifest['history_item_count']} items, {manifest['candidate_count']} candidates)"
    )
    return 0


def cmd_build_variants(args: argparse.Namespace) -> int:
    config_path = Path(args.config).resolve()
    config = json_load(config_path)
    manifest_path = Path(config["history_manifest"]).resolve()
    manifest = json_load(manifest_path)

    errors = validate_variant_config(config, manifest)
    if errors:
        for error in errors:
            log(f"CONFIG ERROR: {error}")
        return 1

    output_dir = prepare_output_dir(Path(config["output_dir"]).resolve())
    projects_dir = output_dir / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)

    variants_manifest: Dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "template_project": config["template_project"],
        "history_manifest": path_to_str(manifest_path),
        "output_dir": path_to_str(output_dir),
        "output_mode": "separate_projects",
        "variants": [],
    }

    rendered_root = output_dir / "rendered_history"
    if args.dump_rendered_history:
        rendered_root.mkdir(parents=True, exist_ok=True)

    session: Optional[CSTSession] = None
    if not args.dry_run:
        session = connect_design_environment(args.connect_to_any, args.options)

    for variant in config["variants"]:
        variant_id = variant["variant_id"]
        variant_name = sanitize_name(variant_id)
        output_path = projects_dir / f"{variant_name}.cst"
        rendered_items, applied_values = render_variant_items(manifest, variant["values"])

        record: Dict[str, Any] = {
            "variant_id": variant_id,
            "output_project": path_to_str(output_path),
            "applied_values": applied_values,
        }

        if args.dump_rendered_history:
            json_dump(
                {
                    "variant_id": variant_id,
                    "rendered_items": rendered_items,
                    "applied_values": applied_values,
                },
                rendered_root / f"{variant_name}.json",
            )

        try:
            if args.dry_run:
                record["status"] = "dry_run"
            else:
                assert session is not None
                rebuild_project_from_history(session, rendered_items, output_path)
                record["status"] = "success"
        except Exception as exc:
            record["status"] = "failed"
            record["error"] = str(exc)
            log(f"Variant '{variant_id}' failed: {exc}")

        variants_manifest["variants"].append(record)

    json_dump(variants_manifest, output_dir / "variants_manifest.json")
    json_dump(config, output_dir / "variant_config.json")

    success_count = sum(1 for item in variants_manifest["variants"] if item["status"] == "success")
    dry_run_count = sum(1 for item in variants_manifest["variants"] if item["status"] == "dry_run")
    failed_count = sum(1 for item in variants_manifest["variants"] if item["status"] == "failed")
    log(
        f"Variant build finished in {output_dir}: "
        f"success={success_count}, dry_run={dry_run_count}, failed={failed_count}"
    )
    return 0 if failed_count == 0 else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="CST unit-cell history inspection and batch variant generation tool."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    info_parser = subparsers.add_parser("info", help="List running CST design environments.")
    info_parser.set_defaults(handler=cmd_info)

    connect_parser = subparsers.add_parser(
        "connect", help="Connect to an existing or new CST design environment."
    )
    connect_parser.add_argument(
        "--connect-to-any",
        action="store_true",
        help="Connect to any running CST instance, or create one if none exists.",
    )
    connect_parser.add_argument(
        "--options",
        nargs="*",
        default=[],
        help="Optional CST startup options, for example: --options -m -i",
    )
    connect_parser.set_defaults(handler=cmd_connect)

    new_mws_parser = subparsers.add_parser(
        "new-mws", help="Create a new Microwave Studio project."
    )
    new_mws_parser.add_argument(
        "--connect-to-any",
        action="store_true",
        help="Connect to any running CST instance, or create one if none exists.",
    )
    new_mws_parser.add_argument(
        "--options",
        nargs="*",
        default=[],
        help="Optional CST startup options, for example: --options -m -i",
    )
    new_mws_parser.add_argument("--save-as", help="Optional target .cst path for saving.")
    new_mws_parser.set_defaults(handler=cmd_new_mws)

    inspect_parser = subparsers.add_parser(
        "inspect-history", help="Open a template project and export a history manifest JSON."
    )
    inspect_parser.add_argument("--project", required=True, help="Path to the template .cst file.")
    inspect_parser.add_argument(
        "--output",
        default="history_manifest.json",
        help="Output JSON path. Defaults to ./history_manifest.json",
    )
    inspect_parser.add_argument(
        "--connect-to-any",
        action="store_true",
        help="Connect to any running CST instance, or create one if none exists.",
    )
    inspect_parser.add_argument(
        "--options",
        nargs="*",
        default=[],
        help="Optional CST startup options, for example: --options -m -i",
    )
    inspect_parser.set_defaults(handler=cmd_inspect_history)

    build_parser_cmd = subparsers.add_parser(
        "build-variants",
        help="Build multiple variant .cst projects from a history manifest and JSON config.",
    )
    build_parser_cmd.add_argument(
        "--config", required=True, help="Path to the variant configuration JSON."
    )
    build_parser_cmd.add_argument(
        "--connect-to-any",
        action="store_true",
        help="Connect to any running CST instance, or create one if none exists.",
    )
    build_parser_cmd.add_argument(
        "--options",
        nargs="*",
        default=[],
        help="Optional CST startup options, for example: --options -m -i",
    )
    build_parser_cmd.add_argument(
        "--dry-run",
        action="store_true",
        help="Render rewritten history and manifests without calling CST.",
    )
    build_parser_cmd.add_argument(
        "--dump-rendered-history",
        action="store_true",
        help="Write each variant's rewritten history to output_dir/rendered_history.",
    )
    build_parser_cmd.set_defaults(handler=cmd_build_variants)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        return args.handler(args)
    except Exception as exc:
        log(f"FAILED: {exc!r}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
