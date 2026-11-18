# Final pilot experiment execution addendum

**Recorded:** 2026-11-16
**Experiment:** `thermoscope_dhanbad_final_pilot_v1`
**Run directory:** `data/processed/final_pilot_experiment/run_001/`

## Status reconciliation

The preflight report at [final_pilot_experiment_preflight.md](final_pilot_experiment_preflight.md) is a historical record created at 2026-11-16 07:01:14 UTC. At that time it correctly reported that the full experiment had not run and that `run_001` did not exist. The run manifest was created later, at 2026-11-16 08:27:47 UTC, and records `run_status: completed`.

The pinned configuration at `config/final_pilot_experiment.json` still contains the earlier lifecycle value `configured_preflight_only_full_run_waits_for_plan_review`. Its SHA-256 is `e4983c4777fb69815953c81a9015a9cd5ce34f78d4f1c6767ba8ac51f885b4b8`, matching the hash recorded in the run manifest. The configuration was not edited: changing it would break the manifest's record of the exact configuration used. Read the manifest as the execution record and the preflight/configuration status as historical planning metadata.

## Audited execution facts

- The manifest records 9,220 observations in each of the prepared FIRMS, spatial matching, feature engineering, and candidate ranking stages.
- The run records 35 of 35 validation checks passed. The manifest also records 51 unit tests passed and Python compile checks passed during execution. These are run-time records; they were not rerun while preparing this addendum.
- Read-only audit confirmed all seven recorded input files and all seven pipeline-script hashes match the values in the manifest. All 47 inventoried output artifacts exist and match their recorded SHA-256 checksums.
- Observation IDs are unique and consistent across the prepared FIRMS, spatial matching, and feature tables. The candidate ranking contains 9,220 unique source-row keys.
- Candidate ranking categories: 6,550 persistent thermal observations with nearby relevant industrial context; 1,921 other thermal observations for review; 556 persistent thermal observations without nearby relevant OSM context; 106 elevated thermal observations without nearby relevant OSM context; 57 elevated thermal observations with nearby relevant industrial context; and 30 persistent thermal observations near general power infrastructure only.
- All 9,220 ranked records remain `unknown_unlinked`. The run contains no verified or weak detection labels and no fabricated negative examples. The ranking categories are investigation priorities, not confirmed causes or classes.
- Sentinel-2 coverage is limited: 11 detections had a temporally eligible scene and two had usable clear pre-detection spectral samples. Missing or unusable optical observations do not indicate absence of thermal activity.
- The manifest records 232.297 seconds elapsed from run-root creation to the last stage artifact write. It records 27,234,146 bytes across the 47 generated files before the manifest was written. Peak disk usage was not sampled.

## Reproducibility and limits

The audit supports internal consistency of the saved run: configuration, input, code, and output checksums agree with the manifest, and stage observation identities align. Checksums are integrity checks, not a cryptographic signature or proof of authorship. Runtime is the manifest's measurement; its whole-second timestamps do not independently reproduce the fractional value. OSM is a static pilot snapshot rather than date-specific historical context. No independently linkable incident records or verified labels were available, so supervised evaluation and claims of verified industrial-fire classification remain unsupported.

No pipeline stage was rerun, no imagery or other data was downloaded, and no historical result, configuration, preflight report, dataset, or notebook was changed to prepare this addendum.
