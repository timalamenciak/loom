"""
LinkML validation wrapper.

Uses the linkml.validator Python API (linkml >= 1.7). Degrades gracefully if
the package is absent or the API shape differs — returns (True, [warning])
rather than crashing.
"""

from __future__ import annotations

import io

import yaml


def validate_graph_data(data: dict, schema_yaml: str) -> tuple[bool, list[str]]:
    """
    Validate a CAMO graph dict against the LinkML schema.

    Returns (is_valid, messages).  Messages include errors first, then warnings.
    is_valid is False only when there are ERROR/FATAL results.
    """
    try:
        from linkml.validator import validate as lm_validate

        data_yaml = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        report = lm_validate(
            data_yaml,
            schema=io.StringIO(schema_yaml),
            target_class="CausalGraph",
            source_file_format="yaml",
        )
        results = list(report.results) if report.results else []
        errors = [r.message for r in results if _is_error(r.severity)]
        warnings = [r.message for r in results if not _is_error(r.severity)]
        return len(errors) == 0, errors + warnings

    except ImportError:
        return True, ["linkml.validator not available — validation skipped"]
    except Exception as exc:
        return False, [f"Validation error: {exc}"]


def _is_error(severity) -> bool:
    s = str(severity).upper()
    return "ERROR" in s or "FATAL" in s or "CRITICAL" in s
