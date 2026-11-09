# Bootstrap Data Completer Schema

## Output files

| path | purpose |
|---|---|
| `.drive/<plan_dir>/bootstrap/diagnosis.json` | gap detection result |
| `.drive/<plan_dir>/bootstrap/completion-spec.yaml` | intermediate spec |
| `.drive/<plan_dir>/bootstrap/patches/*.yaml` | patch candidates for later materialization |
| `.drive/<plan_dir>/bootstrap/validation.json` | structure + intent validation |

## Completion spec fields

- `source_summary`
- `missing_fields`
- `conflicts`
- `completion_strategy`
- `field_mapping`
- `patch_targets`
- `failure_policy`
- `manifest_refs`
- `review_protocol`
- `requires_user_confirmation`
- `confidence`

## Current-field mapping

| inferred source | current drive field |
|---|---|
| workflow entry | `execution_entry` |
| workflow kind | `execution_type` |
| user subagent name | `subagent_type` |
| user skills | `skills` |
| skill outputs / workflow outputs | `expected_outputs` |
| execution order | `steps` |
| pre-read inputs | `read_first_path`, `read_first` |
| owned files | `files_owned` |
| shared dependencies | `shared_files` |
| output contract | `output_schema` |
| review contract | `review_protocol` |
| failure handling | `failure_policy` |
| traceability | `manifest_refs` |
| checks | `verify` |
| acceptance text | `acceptance_criteria` |
| override defaults | `.drive-overrides.yaml` |

## Validation rules

- `confidence` must be explicit.
- `requires_user_confirmation` must be explicit.
- Missing or ambiguous entry shape stays in `diagnosis.json`.
- No direct write to user baseline files.
