import argparse
import csv
import json
import os
import re
import sys
import subprocess
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
IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


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


def get_self_script_path() -> Path:
    return Path(__file__).resolve()


def csv_write_rows(fieldnames: List[str], rows: List[Dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def csv_read_rows(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def try_float(value: Any) -> Optional[float]:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def get_cst_root() -> Path:
    env_value = os.environ.get("CST_ROOT")
    if env_value:
        return Path(env_value).resolve()
    return Path(r"D:\CST")


def bootstrap_cst_python_environment() -> None:
    cst_root = get_cst_root()
    amd64_dir = cst_root / "AMD64"
    python_lib_dir = amd64_dir / "python_cst_libraries"

    if python_lib_dir.exists():
        python_lib_dir_str = str(python_lib_dir)
        if python_lib_dir_str not in sys.path:
            sys.path.insert(0, python_lib_dir_str)

    if amd64_dir.exists():
        amd64_dir_str = str(amd64_dir)
        current_path = os.environ.get("PATH", "")
        path_parts = current_path.split(os.pathsep) if current_path else []
        if amd64_dir_str not in path_parts:
            os.environ["PATH"] = amd64_dir_str + os.pathsep + current_path

        add_dll_directory = getattr(os, "add_dll_directory", None)
        if callable(add_dll_directory):
            try:
                add_dll_directory(amd64_dir_str)
            except OSError:
                pass


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


def _collect_text_fragments(value: Any, seen: Optional[set[int]] = None) -> List[str]:
    if seen is None:
        seen = set()

    object_id = id(value)
    if object_id in seen:
        return []
    seen.add(object_id)

    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []

    if isinstance(value, dict):
        fragments: List[str] = []
        preferred_keys = (
            "content",
            "contents",
            "command",
            "code",
            "text",
            "vba",
            "body",
        )
        for key in preferred_keys:
            if key in value:
                fragments.extend(_collect_text_fragments(value[key], seen))
        for key, child in value.items():
            if key in preferred_keys:
                continue
            fragments.extend(_collect_text_fragments(child, seen))
        return fragments

    if isinstance(value, (list, tuple)):
        fragments: List[str] = []
        for item in value:
            fragments.extend(_collect_text_fragments(item, seen))
        return fragments

    return []


def detect_command_text(history_item: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    for key in ("code", "text", "content", "command", "vba", "body", "contents"):
        value = history_item.get(key)
        fragments = _collect_text_fragments(value)
        if fragments:
            return "\n".join(fragments), key
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


def normalize_parameter_value(value: Any) -> Optional[str]:
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def build_parameter_candidate_id(parameter_name: str) -> str:
    return f"param_{slugify(parameter_name)}"


def extract_project_parameter_references(
    history_index: int,
    history_name: str,
    feature_type: Optional[str],
    command_text: str,
    project_parameters: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    references: List[Dict[str, Any]] = []

    for parameter in sorted(project_parameters, key=lambda item: len(item["name"]), reverse=True):
        name = parameter["name"]
        pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])")
        for ordinal, match in enumerate(pattern.finditer(command_text), start=1):
            line, column = compute_line_column(command_text, match.start())
            references.append(
                {
                    "candidate_id": build_parameter_candidate_id(name),
                    "history_index": history_index,
                    "ordinal": ordinal,
                    "feature_type": feature_type,
                    "history_name": history_name,
                    "parameter_name": name,
                    "suggested_label": name,
                    "source": "project_parameter",
                    "raw_value": match.group(0),
                    "original_expression": parameter.get("string_value") or parameter.get("value"),
                    "original_value": parameter.get("value"),
                    "span": {"start": match.start(), "end": match.end()},
                    "line": line,
                    "column": column,
                }
            )
    references.sort(key=lambda item: (item["span"]["start"], item["span"]["end"]))
    return references


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
                "source": "numeric_literal",
                "raw_value": raw_value,
                "numeric_text": numeric_text,
                "original_value": numeric_value,
                "span": {"start": match.start(), "end": match.end()},
                "line": line,
                "column": column,
            }
        )
    return candidates


def build_parameter_manifest_entries(
    project_parameters: List[Dict[str, Any]],
    references: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    parameter_entries: List[Dict[str, Any]] = []
    refs_by_name: Dict[str, List[Dict[str, Any]]] = {}

    for reference in references:
        refs_by_name.setdefault(reference["parameter_name"], []).append(reference)

    for parameter in project_parameters:
        refs = refs_by_name.get(parameter["name"], [])
        if not refs:
            continue
        parameter_entries.append(
            {
                "candidate_id": build_parameter_candidate_id(parameter["name"]),
                "parameter_name": parameter["name"],
                "suggested_label": parameter["name"],
                "enabled": False,
                "source": "project_parameter",
                "original_value": parameter.get("value"),
                "original_expression": parameter.get("string_value") or parameter.get("value"),
                "usage_count": len(refs),
                "history_indexes": sorted({int(ref["history_index"]) for ref in refs}),
            }
        )
    return parameter_entries


def build_history_manifest(
    project_path: Path,
    history_payload: Dict[str, Any],
    project_parameters: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    history_list = history_payload.get("list") or []
    manifest_items: List[Dict[str, Any]] = []
    flat_candidates: List[Dict[str, Any]] = []
    project_parameters = project_parameters or []
    parameterized_references: List[Dict[str, Any]] = []

    for index, raw_item in enumerate(history_list, start=1):
        history_name = detect_history_name(raw_item, index)
        command_text, command_key = detect_command_text(raw_item)
        feature_type = detect_feature_type(command_text)
        candidates = extract_project_parameter_references(
            index,
            history_name,
            feature_type,
            command_text,
            project_parameters,
        )
        if not candidates and not project_parameters:
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
            "candidates": [
                {
                    key: value
                    for key, value in candidate.items()
                    if key != "enabled"
                }
                for candidate in candidates
            ],
            "raw_item_keys": sorted(raw_item.keys()),
        }
        manifest_items.append(item_entry)
        flat_candidates.extend(deepcopy(candidate) for candidate in candidates)
        parameterized_references.extend(
            deepcopy(candidate)
            for candidate in candidates
            if candidate.get("source") == "project_parameter"
        )

    if parameterized_references:
        flat_parameters = build_parameter_manifest_entries(project_parameters, parameterized_references)
        manifest_mode = "project_parameters"
    else:
        flat_parameters = deepcopy(flat_candidates)
        manifest_mode = "numeric_literals"

    return {
        "schema_version": 2,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "template_project": path_to_str(project_path),
        "parameter_source_mode": manifest_mode,
        "history_item_count": len(manifest_items),
        "candidate_count": len(flat_candidates),
        "parameter_count": len(flat_parameters),
        "items": manifest_items,
        "parameters": flat_parameters,
        "candidates": flat_parameters,
    }


def normalize_manifest(manifest: Dict[str, Any]) -> Dict[str, Any]:
    normalized = deepcopy(manifest)
    item_candidates_by_id: Dict[str, Dict[str, Any]] = {}

    for item in normalized.get("items", []):
        for candidate in item.get("candidates", []):
            candidate_id = candidate.get("candidate_id")
            if candidate_id:
                item_candidates_by_id[candidate_id] = candidate

    top_level_candidates = (
        normalized.get("parameters")
        or normalized.get("candidates")
        or []
    )
    merged_candidates: List[Dict[str, Any]] = []
    seen_ids = set()

    for candidate in top_level_candidates:
        candidate_id = candidate.get("candidate_id")
        if not candidate_id:
            continue
        merged = deepcopy(candidate)
        item_candidate = item_candidates_by_id.get(candidate_id)
        if item_candidate is not None:
            # The top-level parameter list is canonical.
            merged["enabled"] = bool(merged.get("enabled", False))
            for key in (
                "suggested_label",
                "parameter_name",
                "source",
                "original_expression",
                "original_value",
            ):
                if item_candidate.get(key) and not merged.get(key):
                    merged[key] = item_candidate[key]
        merged_candidates.append(merged)
        seen_ids.add(candidate_id)

    for candidate_id, item_candidate in item_candidates_by_id.items():
        if candidate_id not in seen_ids:
            merged = deepcopy(item_candidate)
            merged["enabled"] = bool(merged.get("enabled", False))
            merged_candidates.append(merged)

    by_id = {candidate["candidate_id"]: candidate for candidate in merged_candidates}
    for item in normalized.get("items", []):
        synced_candidates: List[Dict[str, Any]] = []
        for candidate in item.get("candidates", []):
            candidate_id = candidate.get("candidate_id")
            if candidate_id and candidate_id in by_id:
                synced = deepcopy(by_id[candidate_id])
                synced.pop("enabled", None)
                synced_candidates.append(synced)
            else:
                synced_candidates.append(candidate)
        item["candidates"] = synced_candidates

    normalized["parameters"] = merged_candidates
    normalized["candidates"] = merged_candidates
    return normalized


def build_candidate_lookup(manifest: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    manifest = normalize_manifest(manifest)
    lookup: Dict[str, Dict[str, Any]] = {}
    for candidate in manifest.get("candidates", []):
        for key in (
            candidate["candidate_id"],
            candidate.get("suggested_label"),
            candidate.get("parameter_name"),
        ):
            if not key:
                continue
            lookup[key] = candidate
    return lookup


def validate_variant_config(config: Dict[str, Any], manifest: Dict[str, Any]) -> List[str]:
    manifest = normalize_manifest(manifest)
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
            if candidate.get("source") == "project_parameter":
                if normalize_parameter_value(value) is None:
                    errors.append(
                        f"Variant '{variant_id}' value for '{key}' must be a non-empty string or number."
                    )
                continue
            if try_float(value) is None:
                errors.append(
                    f"Variant '{variant_id}' value for '{key}' must be numeric, got: {value!r}"
                )
    return errors


def render_variant_items(
    manifest: Dict[str, Any], variant_values: Dict[str, Any]
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    manifest = normalize_manifest(manifest)
    alias_lookup = build_candidate_lookup(manifest)
    applied_values: Dict[str, str] = {}
    by_history_index: Dict[int, List[Dict[str, Any]]] = {}

    for alias, raw_value in variant_values.items():
        candidate = alias_lookup.get(alias)
        if candidate is None or not candidate.get("enabled"):
            continue
        if candidate.get("source") == "project_parameter":
            value = normalize_parameter_value(raw_value)
            if value is None:
                continue
        else:
            numeric_value = try_float(raw_value)
            if numeric_value is None:
                continue
            value = str(numeric_value)
        if candidate.get("source") == "numeric_literal":
            history_index = int(candidate["history_index"])
            by_history_index.setdefault(history_index, []).append(
                {"candidate": candidate, "value": value, "parameter_name": candidate["suggested_label"]}
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
                new_token = replacement["parameter_name"]
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


def collect_enabled_parameters(manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    manifest = normalize_manifest(manifest)
    result: List[Dict[str, Any]] = []
    for parameter in manifest.get("parameters", []):
        if not parameter.get("enabled"):
            continue
        result.append(
            {
                "candidate_id": parameter["candidate_id"],
                "name": parameter.get("parameter_name") or parameter["suggested_label"],
                "default_value": (
                    parameter.get("original_expression")
                    if parameter.get("source") == "project_parameter"
                    else parameter["original_value"]
                ),
                "description": parameter.get("description")
                or parameter.get("comment")
                or parameter.get("history_name")
                or parameter.get("parameter_name")
                or parameter["candidate_id"],
                "source": parameter.get("source", "numeric_literal"),
            }
        )
    return result


def build_parameter_csv_rows(
    manifest: Dict[str, Any],
    variant_ids: Optional[List[str]] = None,
) -> List[Dict[str, str]]:
    manifest = normalize_manifest(manifest)
    rows: List[Dict[str, str]] = []
    parameter_source_mode = manifest.get("parameter_source_mode", "unknown")
    variant_ids = variant_ids or []

    for parameter in manifest.get("parameters", []):
        parameter_name = (
            parameter.get("parameter_name")
            or parameter.get("suggested_label")
            or parameter.get("candidate_id")
            or ""
        )
        history_indexes = parameter.get("history_indexes") or []
        if isinstance(history_indexes, list) and history_indexes:
            index_text = ", ".join(str(item) for item in history_indexes)
        else:
            index_text = str(parameter.get("history_index", "")) if parameter.get("history_index") else ""

        if parameter_source_mode == "project_parameters":
            note = f"used in history items: {index_text}" if index_text else "used in history"
            initial_value = parameter.get("original_expression") or parameter.get("original_value") or ""
        else:
            history_name = parameter.get("history_name") or ""
            feature_type = parameter.get("feature_type") or ""
            note_parts = [part for part in (history_name, feature_type, f"history {index_text}" if index_text else "") if part]
            note = " | ".join(note_parts)
            initial_value = parameter.get("original_value") or ""

        row = {
            "parameter_name": str(parameter_name),
            "comment": str(note),
            "enable": "true" if parameter.get("enabled") else "false",
            "initial_value": str(initial_value),
        }
        for variant_id in variant_ids:
            row[variant_id] = ""
        rows.append(row)
    return rows


def write_parameter_csv(
    manifest: Dict[str, Any],
    csv_path: str | Path,
    variant_ids: Optional[List[str]] = None,
) -> Path:
    csv_path = Path(csv_path).resolve()
    rows = build_parameter_csv_rows(manifest, variant_ids=variant_ids)
    fieldnames = ["parameter_name", "comment", "enable", "initial_value"] + list(variant_ids or [])
    csv_write_rows(
        fieldnames,
        rows,
        csv_path,
    )
    return csv_path


def parse_csv_bool(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "on"}


def update_manifest_from_parameter_csv(
    manifest_path: str | Path,
    parameter_csv_path: str | Path,
    output_manifest_path: str | Path | None = None,
) -> Dict[str, Any]:
    manifest_path = Path(manifest_path).resolve()
    parameter_csv_path = Path(parameter_csv_path).resolve()
    manifest = normalize_manifest(json_load(manifest_path))
    csv_rows = csv_read_rows(parameter_csv_path)

    parameter_lookup: Dict[str, Dict[str, Any]] = {}
    for parameter in manifest.get("parameters", []):
        for key in (
            parameter.get("parameter_name"),
            parameter.get("suggested_label"),
            parameter.get("candidate_id"),
        ):
            if key:
                parameter_lookup[str(key)] = parameter

    for row in csv_rows:
        parameter_name = str(row.get("parameter_name", "")).strip()
        if not parameter_name:
            continue
        parameter = parameter_lookup.get(parameter_name)
        if parameter is None:
            continue

        if "enable" in row:
            parameter["enabled"] = parse_csv_bool(row.get("enable"))

        comment = str(row.get("comment", "")).strip()
        if comment:
            parameter["comment"] = comment
            if parameter.get("source") == "project_parameter":
                parameter["description"] = comment

        initial_value = normalize_parameter_value(row.get("initial_value"))
        if initial_value is not None:
            if parameter.get("source") == "project_parameter":
                parameter["original_expression"] = initial_value
                parameter["original_value"] = initial_value
            else:
                numeric_value = try_float(initial_value)
                if numeric_value is not None:
                    parameter["original_value"] = numeric_value

    updated_manifest = normalize_manifest(manifest)
    target_path = Path(output_manifest_path).resolve() if output_manifest_path else manifest_path
    json_dump(updated_manifest, target_path)
    return updated_manifest


def detect_variant_columns(csv_rows: List[Dict[str, str]]) -> List[str]:
    if not csv_rows:
        return []
    reserved = {"parameter_name", "comment", "enable", "initial_value"}
    ordered_columns = list(csv_rows[0].keys())
    variant_columns: List[str] = []
    for column in ordered_columns:
        if column in reserved:
            continue
        if any(str(row.get(column, "")).strip() for row in csv_rows):
            variant_columns.append(column)
    return variant_columns


def create_variant_config_from_parameter_csv(
    manifest_path: str | Path,
    parameter_csv_path: str | Path,
    output_path: str | Path,
    *,
    template_project: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> Dict[str, Any]:
    manifest_path = Path(manifest_path).resolve()
    parameter_csv_path = Path(parameter_csv_path).resolve()
    output_path = Path(output_path).resolve()

    manifest = normalize_manifest(json_load(manifest_path))
    csv_rows = csv_read_rows(parameter_csv_path)
    variant_columns = detect_variant_columns(csv_rows)

    variants: List[Dict[str, Any]] = []
    for variant_id in variant_columns:
        values: Dict[str, str] = {}
        for row in csv_rows:
            if not parse_csv_bool(row.get("enable")):
                continue
            parameter_name = str(row.get("parameter_name", "")).strip()
            if not parameter_name:
                continue
            variant_value = normalize_parameter_value(row.get(variant_id))
            if variant_value is None:
                continue
            values[parameter_name] = variant_value
        if values:
            variants.append({"variant_id": variant_id, "values": values})

    config = {
        "template_project": str(template_project or manifest.get("template_project", "")),
        "history_manifest": path_to_str(manifest_path),
        "output_dir": str(output_dir or output_path.parent / "variant_output"),
        "output_mode": "separate_projects",
        "variants": variants,
    }
    json_dump(config, output_path)
    return config


def create_variant_config_template(
    manifest_path: str | Path,
    output_path: str | Path,
    *,
    template_project: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> Dict[str, Any]:
    manifest_path = Path(manifest_path).resolve()
    output_path = Path(output_path).resolve()
    manifest = normalize_manifest(json_load(manifest_path))

    enabled_parameters = collect_enabled_parameters(manifest)
    sample_values: Dict[str, str] = {}
    for parameter in enabled_parameters:
        sample_values[parameter["name"]] = str(parameter["default_value"])

    config = {
        "template_project": str(template_project or manifest.get("template_project", "")),
        "history_manifest": path_to_str(manifest_path),
        "output_dir": str(output_dir or output_path.parent / "variant_output"),
        "output_mode": "separate_projects",
        "variants": [
            {
                "variant_id": "variant_001",
                "values": sample_values,
            }
        ],
    }
    json_dump(config, output_path)
    return config


def export_parameter_edit_table(
    project_path: str | Path,
    work_dir: str | Path,
    *,
    table_name: str = "parameter_table.csv",
    manifest_name: str = "history_manifest.json",
    variant_ids: Optional[List[str]] = None,
    connect_to_any: bool = False,
    options: Optional[List[str]] = None,
) -> Dict[str, Any]:
    work_dir = Path(work_dir).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = work_dir / manifest_name
    csv_path = work_dir / table_name

    manifest = export_history_manifest(
        project_path=project_path,
        output_path=manifest_path,
        parameter_csv_path=csv_path,
        connect_to_any=connect_to_any,
        options=options,
    )
    if variant_ids:
        write_parameter_csv(manifest, csv_path, variant_ids=variant_ids)

    return {
        "manifest_path": path_to_str(manifest_path),
        "parameter_csv_path": path_to_str(csv_path),
        "history_item_count": manifest["history_item_count"],
        "parameter_count": manifest.get("parameter_count", 0),
    }


def import_parameter_table_and_build(
    manifest_path: str | Path,
    parameter_csv_path: str | Path,
    *,
    variant_config_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    connect_to_any: bool = False,
    options: Optional[List[str]] = None,
    dry_run: bool = False,
    dump_rendered_history: bool = False,
) -> Dict[str, Any]:
    manifest_path = Path(manifest_path).resolve()
    parameter_csv_path = Path(parameter_csv_path).resolve()
    if variant_config_path is None:
        variant_config_path = manifest_path.with_name("variant_config.json")
    variant_config_path = Path(variant_config_path).resolve()

    updated_manifest = update_manifest_from_parameter_csv(
        manifest_path=manifest_path,
        parameter_csv_path=parameter_csv_path,
    )

    config = create_variant_config_from_parameter_csv(
        manifest_path=manifest_path,
        parameter_csv_path=parameter_csv_path,
        output_path=variant_config_path,
        output_dir=output_dir,
    )

    variants_manifest = build_variants_from_config(
        config_path=variant_config_path,
        connect_to_any=connect_to_any,
        options=options,
        dry_run=dry_run,
        dump_rendered_history=dump_rendered_history,
    )

    return {
        "updated_manifest": updated_manifest,
        "variant_config": config,
        "variants_manifest": variants_manifest,
        "variant_config_path": path_to_str(variant_config_path),
    }


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
    bootstrap_cst_python_environment()
    from cst.interface import DesignEnvironment, Project, running_design_environments

    return DesignEnvironment, Project, running_design_environments


def import_cst_project_class():
    _, Project, _ = import_cst_interface()
    return Project


def connect_design_environment(connect_to_any: bool, options: Optional[List[str]]) -> CSTSession:
    DesignEnvironment, _, _ = import_cst_interface()
    if connect_to_any:
        de = DesignEnvironment.connect_to_any_or_new()
    else:
        de = DesignEnvironment.new(options=options or None)
    return CSTSession(design_environment=de)


def _normalize_project_path(value: Any) -> Optional[Path]:
    if value is None:
        return None
    try:
        return Path(str(value)).resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def find_open_project(session: CSTSession, project_path: Path) -> Tuple[Optional[Any], Optional[str]]:
    de = session.design_environment
    target_path = _normalize_project_path(project_path)
    if target_path is None:
        return None, None

    try:
        open_projects = list(de.list_open_projects())
    except Exception:
        open_projects = []

    for open_name in open_projects:
        if _normalize_project_path(open_name) != target_path:
            continue
        try:
            return de.get_open_project(open_name), open_name
        except Exception:
            continue
    return None, None


def open_project(session: CSTSession, project_path: Path) -> Any:
    existing_project, _ = find_open_project(session, project_path)
    if existing_project is not None:
        return existing_project
    return session.design_environment.open_project(str(project_path))


def read_history_payload(project: Any) -> Dict[str, Any]:
    history = project.model3d._GetHistory()
    if not isinstance(history, dict):
        raise RuntimeError("CST returned an unexpected history payload type.")
    return history


def try_get_project_parameter_methods(project: Any) -> Optional[Any]:
    for source in (project, getattr(project, "schematic", None), getattr(project, "model3d", None)):
        if source is None:
            continue
        if hasattr(source, "GetNumberOfParameters") and hasattr(source, "GetParameterName"):
            return source
    return None


def read_project_parameters(project: Any) -> List[Dict[str, Any]]:
    source = try_get_project_parameter_methods(project)
    if source is None:
        return []

    try:
        count = int(source.GetNumberOfParameters())
    except Exception:
        return []

    if count <= 0:
        return []

    def collect_with_indices(indices: Iterable[int]) -> List[Dict[str, Any]]:
        parameters: List[Dict[str, Any]] = []
        for index in indices:
            try:
                name = source.GetParameterName(index)
            except Exception:
                return []
            if not name:
                return []
            try:
                string_value = source.GetParameterSValue(index)
            except Exception:
                string_value = None
            try:
                numeric_value = source.GetParameterNValue(index)
            except Exception:
                numeric_value = None
            parameters.append(
                {
                    "index": index,
                    "name": str(name).strip(),
                    "value": normalize_parameter_value(string_value)
                    or normalize_parameter_value(numeric_value),
                    "string_value": normalize_parameter_value(string_value),
                    "numeric_value": try_float(numeric_value),
                }
            )
        return [parameter for parameter in parameters if parameter["name"]]

    for indices in (range(count), range(1, count + 1)):
        parameters = collect_with_indices(indices)
        if parameters:
            return parameters
    return []


def read_project_parameters_from_path(
    project_path: str | Path,
    *,
    connect_to_any: bool = False,
    options: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    project_path = Path(project_path).resolve()
    session = connect_design_environment(connect_to_any, options or [])
    project = open_project(session, project_path)
    return read_project_parameters(project)


def export_history_manifest(
    project_path: str | Path,
    output_path: str | Path | None = None,
    *,
    parameter_csv_path: str | Path | None = None,
    connect_to_any: bool = False,
    options: Optional[List[str]] = None,
) -> Dict[str, Any]:
    project_path = Path(project_path).resolve()
    session = connect_design_environment(connect_to_any, options or [])
    project = open_project(session, project_path)
    project_parameters = read_project_parameters(project)
    history_payload = read_history_payload(project)
    manifest = build_history_manifest(project_path, history_payload, project_parameters)
    if output_path is not None:
        output_path = Path(output_path).resolve()
        json_dump(manifest, output_path)
        if parameter_csv_path is None:
            parameter_csv_path = output_path.with_name(f"{output_path.stem}_parameters.csv")
    if parameter_csv_path is not None:
        write_parameter_csv(manifest, Path(parameter_csv_path).resolve())
    return manifest


def build_variants_from_config(
    config_path: str | Path,
    *,
    connect_to_any: bool = False,
    options: Optional[List[str]] = None,
    dry_run: bool = False,
    dump_rendered_history: bool = False,
) -> Dict[str, Any]:
    config_path = Path(config_path).resolve()
    config = json_load(config_path)
    required_keys = {"template_project", "history_manifest", "output_dir", "variants"}
    missing_keys = sorted(required_keys - set(config.keys()))
    if missing_keys:
        raise ValueError(
            "The given config_path does not point to a valid variant_config.json. "
            f"Missing keys: {', '.join(missing_keys)}. "
            "You probably passed history_manifest.json by mistake."
        )
    manifest_path = Path(config["history_manifest"]).resolve()
    manifest = json_load(manifest_path)
    template_project_path = Path(config["template_project"]).resolve()

    errors = validate_variant_config(config, manifest)
    if errors:
        raise ValueError("\n".join(errors))

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
    if dump_rendered_history:
        rendered_root.mkdir(parents=True, exist_ok=True)

    session: Optional[CSTSession] = None
    if not dry_run and manifest.get("parameter_source_mode") != "project_parameters":
        session = connect_design_environment(connect_to_any, options or [])

    project_parameters = collect_enabled_parameters(manifest)

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

        if dump_rendered_history:
            json_dump(
                {
                    "variant_id": variant_id,
                    "rendered_items": rendered_items,
                    "applied_values": applied_values,
                },
                rendered_root / f"{variant_name}.json",
            )

        try:
            if dry_run:
                record["status"] = "dry_run"
            else:
                if manifest.get("parameter_source_mode") == "project_parameters":
                    run_single_variant_build_subprocess(
                        template_project_path,
                        output_path,
                        project_parameters,
                        applied_values,
                    )
                else:
                    assert session is not None
                    with session.design_environment.quiet_mode_enabled():
                        rebuild_project_from_history(
                            session,
                            rendered_items,
                            output_path,
                            project_parameters,
                            applied_values,
                        )
                record["status"] = "success"
        except Exception as exc:
            record["status"] = "failed"
            record["error"] = str(exc)
            log(f"Variant '{variant_id}' failed: {exc}")

        variants_manifest["variants"].append(record)

    json_dump(variants_manifest, output_dir / "variants_manifest.json")
    json_dump(config, output_dir / "variant_config.json")
    return variants_manifest


def rebuild_project_from_history(
    session: CSTSession,
    rendered_items: List[Dict[str, Any]],
    output_path: Path,
    project_parameters: List[Dict[str, Any]],
    applied_values: Dict[str, float],
) -> None:
    project = session.design_environment.new_mws()
    model3d = project.model3d
    schematic = project.schematic

    for parameter in project_parameters:
        value = applied_values.get(parameter["candidate_id"], parameter["default_value"])
        try:
            schematic.StoreParameterWithDescription(
                parameter["name"], value, parameter["description"]
            )
        except Exception:
            schematic.StoreParameter(parameter["name"], value)

    for item in rendered_items:
        command_text = item.get("command_text") or ""
        if not command_text.strip():
            continue
        model3d.add_to_history(item["name"], command_text)

    model3d.full_history_rebuild()
    save_project_state(project, output_path, include_results=False)
    close_project_after_save(project)


def save_project_state(project: Any, output_path: Path, include_results: bool = False) -> None:
    output_path = Path(output_path).resolve()

    save_as_method = getattr(project, "SaveAs", None)
    if callable(save_as_method):
        save_as_method(str(output_path), include_results)
        return

    save_method = getattr(project, "save", None)
    if callable(save_method):
        try:
            save_method(str(output_path), include_results=include_results)
            return
        except TypeError:
            try:
                save_method(str(output_path), include_results)
                return
            except TypeError:
                save_method()
                return

    save_plain_method = getattr(project, "Save", None)
    if callable(save_plain_method):
        save_plain_method()
        return

    raise RuntimeError("No supported CST project save method was found.")


def close_project_after_save(project: Any) -> None:
    for method_name in ("close", "Close"):
        close_method = getattr(project, method_name, None)
        if callable(close_method):
            try:
                close_method()
            except Exception:
                pass
            return


def get_parameter_store_target(project: Any) -> Any:
    for target in (project, getattr(project, "schematic", None)):
        if target is None:
            continue
        if hasattr(target, "StoreParameter"):
            return target
    raise RuntimeError("No supported CST parameter store target was found.")


def apply_parameters_to_project(project: Any, project_parameters: List[Dict[str, Any]], applied_values: Dict[str, str]) -> None:
    target = get_parameter_store_target(project)
    for parameter in project_parameters:
        value = applied_values.get(parameter["candidate_id"], parameter["default_value"])
        try:
            target.StoreParameterWithDescription(
                parameter["name"], value, parameter["description"]
            )
        except Exception:
            target.StoreParameter(parameter["name"], value)


def build_variant_project_from_template(
    template_project_path: Path,
    output_path: Path,
    project_parameters: List[Dict[str, Any]],
    applied_values: Dict[str, str],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    import shutil

    shutil.copy2(template_project_path, output_path)
    Project = import_cst_project_class()
    project = Project.open(str(output_path))
    apply_parameters_to_project(project, project_parameters, applied_values)
    try:
        project.model3d.full_history_rebuild()
    except Exception:
        pass
    save_project_state(project, output_path, include_results=False)
    close_project_after_save(project)


def run_single_variant_build_subprocess(
    template_project_path: Path,
    output_path: Path,
    project_parameters: List[Dict[str, Any]],
    applied_values: Dict[str, str],
) -> None:
    task = {
        "template_project_path": path_to_str(template_project_path),
        "output_path": path_to_str(output_path),
        "project_parameters": project_parameters,
        "applied_values": applied_values,
    }
    task_path = output_path.with_suffix(".build-task.json")
    json_dump(task, task_path)

    cmd = [
        sys.executable,
        str(get_self_script_path()),
        "build-single-variant",
        "--task",
        str(task_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        task_path.unlink(missing_ok=True)
    except OSError:
        pass

    if result.returncode != 0:
        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        details = "\n".join(part for part in (stdout, stderr) if part)
        raise RuntimeError(details or f"Single variant subprocess failed with code {result.returncode}")


def cmd_build_single_variant(args: argparse.Namespace) -> int:
    task = json_load(Path(args.task).resolve())
    build_variant_project_from_template(
        template_project_path=Path(task["template_project_path"]).resolve(),
        output_path=Path(task["output_path"]).resolve(),
        project_parameters=task["project_parameters"],
        applied_values=task["applied_values"],
    )
    return 0


def cmd_info(_: argparse.Namespace) -> int:
    _, _, running_design_environments = import_cst_interface()
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
    parameter_csv_path = (
        Path(args.parameters_csv).resolve()
        if args.parameters_csv
        else output_path.with_name(f"{output_path.stem}_parameters.csv")
    )
    log(f"Inspecting history from: {project_path}")
    manifest = export_history_manifest(
        project_path,
        output_path,
        parameter_csv_path=parameter_csv_path,
        connect_to_any=args.connect_to_any,
        options=args.options,
    )

    log(
        f"History manifest written: {output_path} "
        f"({manifest['history_item_count']} items, {manifest['candidate_count']} candidates)"
    )
    log(f"Parameter CSV written: {parameter_csv_path}")
    return 0


def cmd_build_variants(args: argparse.Namespace) -> int:
    try:
        variants_manifest = build_variants_from_config(
            args.config,
            connect_to_any=args.connect_to_any,
            options=args.options,
            dry_run=args.dry_run,
            dump_rendered_history=args.dump_rendered_history,
        )
    except ValueError as exc:
        for line in str(exc).splitlines():
            log(f"CONFIG ERROR: {line}")
        return 1

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
        "--parameters-csv",
        help=(
            "Optional CSV path for a simplified parameter table. "
            "Defaults to <output_stem>_parameters.csv in the same folder."
        ),
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

    single_variant_parser = subparsers.add_parser(
        "build-single-variant",
        help=argparse.SUPPRESS,
    )
    single_variant_parser.add_argument("--task", required=True, help=argparse.SUPPRESS)
    single_variant_parser.set_defaults(handler=cmd_build_single_variant)

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
