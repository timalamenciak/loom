"""Tests for the UpdateCheckRecord model's upsert-on-check contract."""

from apps.schemas.models import UpdateCheckRecord


class TestUpdateCheckRecordUpsert:
    def test_update_check_record_upsert(self, db):
        UpdateCheckRecord.objects.update_or_create(
            module_type="schema",
            module_name="camo",
            defaults={
                "current_version": "0.4.0",
                "available_version": "0.5.0",
                "is_update_available": True,
                "release_notes": "first check",
                "diff_summary": {"added_slots": ["x"]},
                "download_url": "https://example/a.yaml",
            },
        )
        UpdateCheckRecord.objects.update_or_create(
            module_type="schema",
            module_name="camo",
            defaults={
                "current_version": "0.4.0",
                "available_version": "0.6.0",
                "is_update_available": True,
                "release_notes": "second check",
                "diff_summary": {"added_slots": ["x", "y"]},
                "download_url": "https://example/b.yaml",
            },
        )

        assert UpdateCheckRecord.objects.count() == 1
        record = UpdateCheckRecord.objects.get(module_type="schema", module_name="camo")
        assert record.available_version == "0.6.0"
        assert record.release_notes == "second check"
        assert record.diff_summary == {"added_slots": ["x", "y"]}
        assert record.download_url == "https://example/b.yaml"
