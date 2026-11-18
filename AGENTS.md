# ThermoScope project instructions

## Project purpose
ThermoScope analyzes satellite thermal observations using NASA FIRMS, OpenStreetMap (OSM), temporal recurrence, and Sentinel-2 imagery. The current research scope is evidence-based candidate prioritization in the Dhanbad–Jharia–Bokaro pilot. It is not a verified automatic industrial-fire classifier.

## Preserve existing work
- Never delete, reset, overwrite, or discard existing notebooks.
- Never delete or overwrite raw or processed datasets.
- Preserve existing experiment outputs and historical results.
- Never run `git reset --hard`, `git clean`, or destructive cleanup commands.
- Never discard uncommitted changes.

## Git safety
- Inspect `git status` before modifying files.
- Do not commit, push, merge, or rebase without explicit user approval.
- Do not stage unrelated files.
- Keep changes limited to the requested task.

## Data safety
- Do not download large datasets or launch nationwide processing without explicit approval.
- Reuse valid local data and caches.
- Do not invent labels, negative samples, or model performance metrics.
- Record provenance and reproducibility information.

## Scientific integrity
- Distinguish thermal detections from confirmed fires.
- Treat OSM proximity and recurrence as evidence, not causal proof.
- Treat Sentinel-2 as optical context, not thermal confirmation.
- Never claim supervised classification accuracy without credible labels.

## Development workflow
- Use the existing Python environment and project dependencies.
- Run relevant tests after modifications.
- Report test results, files changed, and limitations.
- Explain failures rather than silently skipping them.

## Communication
- Work on one requested task at a time.
- Explain important changes in simple language.
- Do not make unrelated improvements.
