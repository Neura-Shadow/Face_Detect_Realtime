# Phase 12D-VLM-TRIGGER-SCAFFOLD - VLM Trigger Ablation Prepared

## Status

```text
Phase 12D-VLM-TRIGGER-SCAFFOLD Prepared - VLM trigger/no-VLM ablation matrix, command wiring, and evidence schema are implemented without running CARLA or external VLM calls.
```

Phase 12D fixes the stable control path at `controller_mode=grp_follower`,
`perception_backend=dummy`, `town=Town03`, and the five calibrated Phase 12A-C
routes. Only VLM mode varies. Dummy is selected solely as the stable
control-path baseline; this experiment does not compare perception quality.

## Matrix

| VLM mode | VLM enabled | provider | force interval | provider policy |
| --- | ---: | --- | ---: | --- |
| `vlm_disabled` | false | `none` | 0 | Always available; local planner path only |
| `local_stub_event_triggered` | true | `local_stub` | 0 | Always available; normal TriggerPolicy |
| `local_stub_forced_every_20` | true | `local_stub` | 20 | Always available; forced trigger every 20 frames |
| `openai_compatible_optional` | true | `openai_compatible` | 0 | Optional; unavailable configuration marks rows `provider_unavailable` |

Each mode is crossed with these calibrated routes:

| route_id | spawn pair | horizon | target speed | sampling | lookahead |
| --- | --- | ---: | ---: | ---: | ---: |
| `route_01` | 3 -> 30 | 2500 | 18 km/h | 2.0 m | 8 |
| `route_02` | 8 -> 52 | 2800 | 18 km/h | 2.0 m | 8 |
| `route_03` | 12 -> 74 | 2500 | 18 km/h | 2.0 m | 8 |
| `route_04` | 25 -> 101 | 2500 | 18 km/h | 2.0 m | 8 |
| `route_05` | 40 -> 126 | 5400 | 8 km/h | 1.0 m | 3 |

The unfiltered matrix therefore contains `5 routes x 4 modes = 20 rows`.
`--route-id` and `--vlm-mode` can create a smaller review subset without
changing the canonical matrix.

## Command Wiring

The parent scaffold does not import `carla` and never launches a child process.
It writes replayable Phase 11M commands using the existing route and VLM paths:

- `--enable-vlm` enables the optional VLM branch.
- `--vlm-provider local_stub|openai_compatible` selects the existing provider abstraction.
- `--force-vlm-every 20` uses the existing TriggerPolicy interval override.
- no VLM flags means local-planner-only control.

Phase 11M now forwards `--vlm-provider` into `AgentConfig.vlm.provider`; CARLA,
GRP, planner, SafetyGate, VLM reasoner, and control behavior are otherwise
unchanged.

## Provider Readiness

The OpenAI-compatible preflight uses only the existing configuration contract:
`VLM_API_BASE`, `VLM_MODEL`, and `VLM_API_KEY`. The current reasoner accepts
`VLM_API_KEY=optional` for endpoints that do not require authentication, so
readiness requires a configured API base, model, and local `httpx` dependency.
Only missing field names are recorded; values and secrets are never serialized.

Latest local dry-run evidence:

```text
evidence_dir=experiments\phase12\20260713T174823Z
row_count=20
route_count=5
vlm_mode_count=4
vlm_disabled_available=true
local_stub_event_triggered_available=true
local_stub_forced_every_20_available=true
openai_compatible_optional_available=false
openai_compatible_missing=VLM_MODEL
provider_unavailable_count=5
runtime_executed=false
external_vlm_request_executed=false
```

Absent OpenAI-compatible configuration is an optional provider blocker, not a
scaffold failure. No API endpoint was contacted during preflight.

## Evidence Schema

Every row records route identity, fixed controller/perception values, VLM mode,
provider, force interval, provider readiness, result, and the prepared child
command. Runtime aggregation fields are present but remain JSON `null`:

```text
fixed_route_goal_reached
distance_to_goal_m
route_progress_pct
collision_count
lane_invasion_count
steps_completed
vlm_trigger_count
vlm_request_count
vlm_success_count
vlm_fallback_count
vlm_parse_failure_count
vlm_avg_latency_ms
vlm_p95_latency_ms
trigger_rate_per_100_steps
local_planner_action_count
semantic_planner_action_count
safety_gate_accept_count
safety_gate_reject_count
planner_override_count
control_source_local_count
control_source_semantic_count
decision_cycle_avg_ms
total_runtime_sec
```

Each local evidence directory contains:

```text
manifest.json
summary.csv
summary.json
commands.txt
README.md
```

Generated evidence remains under `experiments\phase12` and is ignored by git.

## Usage

```powershell
python scripts\run_phase12d_vlm_trigger_ablation.py --dry-run --output-dir experiments\phase12
```

Optional filtered review:

```powershell
python scripts\run_phase12d_vlm_trigger_ablation.py --dry-run --route-id route_01 --vlm-mode local_stub_event_triggered --output-dir experiments\phase12
```

The scaffold rejects execution without `--dry-run`. The next implementation
line is `Phase 12D-VLM-TRIGGER-WIRING`.

## Boundary

```text
carla_server_started=false
runtime_executed=false
external_vlm_request_executed=false
full_phase12d_runtime_pass=false
full_phase12c_perception_ablation_runtime_pass=false
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
```

This phase is not VLM accuracy evidence, perception quality evidence, a route
benchmark, CARLA Leaderboard evaluation, or an infraction benchmark. No CARLA
runtime or external API request was executed, and no secrets are committed.
