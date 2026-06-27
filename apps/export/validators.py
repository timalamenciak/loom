"""Fail-closed LinkML validation wrappers."""

from __future__ import annotations

import inspect
import io

import yaml


def validate_graph_data(data: dict, schema_yaml: str) -> tuple[bool, list[str]]:
    """Validate a CAMO graph dict against its pinned LinkML schema."""
    return validate_instance_data(data, schema_yaml, target_class="CausalGraph")


def validate_instance_data(
    data: dict, schema_yaml: str, *, target_class: str
) -> tuple[bool, list[str]]:
    """Validate one LinkML class instance and return ``(valid, messages)``.

    LinkML changed its convenience API between supported releases. Detect the
    callable shape explicitly so a dependency update cannot silently skip
    validation.
    """
    try:
        from linkml.validator import validate as lm_validate

        parameters = inspect.signature(lm_validate).parameters
        if "source_file_format" in parameters:
            data_yaml = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
            report = lm_validate(
                data_yaml,
                schema=io.StringIO(schema_yaml),
                target_class=target_class,
                source_file_format="yaml",
            )
        else:
            report = lm_validate(
                data,
                schema=yaml.safe_load(schema_yaml),
                target_class=target_class,
            )

        results = list(report.results) if report.results else []
        errors = [r.message for r in results if _is_error(r.severity)]
        warnings = [r.message for r in results if not _is_error(r.severity)]
        return len(errors) == 0, errors + warnings
    except ImportError:
        return False, ["linkml.validator is unavailable; validation cannot run"]
    except Exception as exc:
        return False, [f"Validation error: {exc}"]


def _is_error(severity) -> bool:
    value = str(severity).upper()
    return "ERROR" in value or "FATAL" in value or "CRITICAL" in value
