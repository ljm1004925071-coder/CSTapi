---
name: cst-python-automation
description: Use when an agent needs to control CST Studio Suite from natural-language requests, including connecting to or launching CST, opening or reusing .cst projects, editing parameters, adding/removing geometry, configuring simulations, running solvers, reading S-parameters/farfields/efficiency/logs, optimization loops, and machine-learning or deep-learning surrogate workflows.
---

# CST Natural-Language Automation Skill

## 1. Purpose

Translate a user's high-level CST request into a safe, verifiable, reproducible Python automation workflow. Do not stop at conceptual advice: identify project paths, operations, save policy, result-reading method, logs, and artifacts.

## 2. Official Source Priority

Consult official references before generating CST commands.

1. Python API: `official-docs/python/`, especially `main.html`, `source/cst.interface.html`, and `source/cst.results.html`.
2. Python package source: `official-docs/python_cst_libraries/cst/`, especially `interface/studio.py` and `results.py`.
3. 3D modeling and History/VBA commands: `official-docs/vba-3d/`.
4. Design Studio / schematic commands: `official-docs/vba-des/`.
5. Launch, OLE automation, and environment variables: `official-docs/advanced/`.
6. If copied docs are insufficient, use `official-docs/source-index.md` to inspect the full CST installation under `D:\CST`.

Core split:

- `cst.interface`: connect to CST, create/open/reuse projects, run solvers, access 3D/Schematic applications.
- `cst.results`: read 0D/1D/2D results from saved `.cst` files without launching CST.
- VBA/History: build geometry, ports, materials, boundaries, mesh, monitors, and solver settings.
- `model3d.add_to_history(header, vba_code)`: the main bridge for Python-driven CST modeling.

## 3. Intent Parsing Protocol

Normalize the user request into a task spec first:

```yaml
task_type: connect | parameter_edit | geometry_edit | build_model | simulate | read_results | optimize | ml_loop
project_path: path-or-null
save_policy: no_save | save_copy | save_original
parameters: name/value pairs
geometry_ops: add/remove/replace operations
solver: time_domain | frequency_domain | existing
metrics: S11, S21, bandwidth, gain, efficiency, farfield, logs
budget: simulation count or time limit
risk_level: low | medium | high
outputs: expected project, dataset, metrics, plots, logs
```

Discover repo and project facts before asking the user. Ask only for risky preferences such as saving originals, deleting geometry, running long simulations, or overwriting GitHub.

## 4. Execution Decision Tree

- Connect/test CST: use `DesignEnvironment.connect_to_any_or_new()`; if the user requires an already-open project, fail when no visible Design Environment exists.
- Edit parameters: read originals, write new values, rebuild; default to not saving the original project.
- Build a new model: create MWS, store parameters, add setup, geometry, ports, solver settings, rebuild, save to a new path.
- Add/remove geometry: prefer a copied project and apply History/VBA operations there.
- Read results: prefer offline `cst.results.ProjectFile`; use live CST only when unsaved or real-time data is required.
- Run simulation: copy to a job directory, apply parameters, rebuild, run solver, read logs and metrics.
- Optimize or use ML: treat CST as the expensive ground-truth evaluator; record every trial with parameters, metrics, status, logs, and project path.

## 5. Core Workflows

### Build A New Model

1. Extract frequency, dimensions, materials, ports, boundaries, and target metrics.
2. Build a parameter table; keep dimensions parameterized.
3. Use `DesignEnvironment.new()` or `connect_to_any_or_new()`, then `new_mws()`.
4. Store parameters with `StoreParameterWithDescription` or `StoreParameter`.
5. Use `add_to_history()` for units, frequency range, background, boundaries, mesh, and monitors.
6. Add components, materials, geometry, ports, and lumped elements.
7. Add solver settings.
8. Run `full_history_rebuild()`, falling back to `RebuildOnParametricChange(True, False)`.
9. Save to a new `.cst` path.

### Modify An Existing Project

1. Connect to CST and inspect `list_open_projects()`.
2. If the user asks for live modification of an open project, reuse it via `get_open_project()`.
3. Read original parameter values before writing.
4. Write new values and rebuild.
5. Follow the save policy: restore/no-save, save copy, or save original.

### Run Simulation

1. Copy the `.cst` file and same-name project folder into a job directory.
2. Remove stale `.lok` files from the copied project folder.
3. Open the copied project, apply parameters, and rebuild.
4. Use `model3d.run_solver()`, falling back to `RunSolver()`.
5. Inspect `Result/Model.log`, `output.json`, and `outputDS.json`.
6. Read metrics and write `metrics.json` or `trials.jsonl`.

### Read Results

1. Prefer `ProjectFile(path, allow_interactive=False)` for saved projects.
2. Use `get_3d().get_tree_items()` to discover tree paths; do not hard-code paths first.
3. Match `S-Parameters`, `Farfields`, `Efficiencies`, and other requested items.
4. Use `get_result_item(treepath).get_xdata()` and `get_ydata()` for 1D curves.
5. Report the metric source: live API, `cst.results`, exported text, or parsed logs.

## 6. Modeling And Simulation Command Pattern

History helper:

```python
def add_history(project, caption, lines):
    project.model3d.add_to_history(caption, "\n".join(lines) + "\n")
```

Minimal setup:

```python
add_history(project, "setup units boundary monitor", [
    "With Units",
    '    .SetUnit "Length", "mm"',
    '    .SetUnit "Frequency", "GHz"',
    "End With",
    'Solver.FrequencyRange "fmin", "fmax"',
    "With Boundary",
    '    .Xmin "expanded open"',
    '    .Xmax "expanded open"',
    '    .Ymin "expanded open"',
    '    .Ymax "expanded open"',
    '    .Zmin "expanded open"',
    '    .Zmax "expanded open"',
    "End With",
    "With Monitor",
    "    .Reset",
    '    .Name "farfield (f=fmon)"',
    '    .Domain "Frequency"',
    '    .FieldType "Farfield"',
    '    .MonitorValue "fmon"',
    "    .Create",
    "End With",
])
```

Brick example:

```python
add_history(project, "create patch", [
    "With Brick",
    "    .Reset",
    '    .Name "patch"',
    '    .Component "metal"',
    '    .Material "PEC"',
    '    .Xrange "-patch_w/2", "patch_w/2"',
    '    .Yrange "-patch_l/2", "patch_l/2"',
    '    .Zrange "0", "metal_t"',
    "    .Create",
    "End With",
])
```

Discrete port example:

```python
add_history(project, "define port 1", [
    "With DiscretePort",
    "    .Reset",
    '    .PortNumber "1"',
    '    .Type "SParameter"',
    '    .Impedance "50.0"',
    '    .SetP1 "False", "feed_x", "-feed_gap/2", "0"',
    '    .SetP2 "False", "feed_x", "feed_gap/2", "0"',
    "    .Create",
    "End With",
])
```

Run solver:

```python
try:
    project.model3d.full_history_rebuild()
except Exception:
    project.model3d.RebuildOnParametricChange(True, False)

try:
    project.model3d.run_solver()
except Exception:
    project.model3d.RunSolver()
```

## 7. Optimization And Deep Learning Loops

- Parameter search: define variables, bounds, objective, constraints, and budget; copy and simulate each candidate; cache evaluated parameters.
- Surrogate modeling: generate a CST dataset and train a model to predict S-parameters, bandwidth, gain, efficiency, or farfield scores.
- Active learning: let the surrogate propose candidates, validate valuable samples in CST, append data, and retrain.
- Inverse design: optimize on the surrogate first, then validate top-k designs in CST.
- Write every trial to `trials.jsonl` with parameters, metrics, status, errors, project path, and log path.

## 8. Safety Rules

- Do not save the user's original project by default.
- Use copied projects for geometry deletion, overwrites, long simulations, and batch optimization unless explicitly requested otherwise.
- Never recursively delete `pdfsrc`, junctions, symlinks, or external linked directories.
- Do not infer CST is controllable from backend processes such as `cstd`; check `running_design_environments()`.
- Do not confuse "read existing results" with "run a new simulation".
- Do not hard-code result tree paths before discovering available tree items.

## 9. Output Contract

Every completed task should report:

```yaml
project_path: used or generated CST project
save_policy: no_save | save_copy | save_original
operations: list of parameter/modeling/simulation steps
metrics: extracted values with source
logs: Model.log/output.json/outputDS.json paths
artifacts: generated files, datasets, plots, manifests
warnings: assumptions, skipped steps, risks
errors: failures and recovery attempts
```

