"""Tests for apps/annotation/utils.py"""

from unittest.mock import patch


class TestCalculateStudyDuration:
    """Test the calculate_study_duration_months function."""

    def test_same_month(self):
        from apps.annotation.utils import calculate_study_duration_months

        assert calculate_study_duration_months("2020-01", "2020-01") == 0.0

    def test_one_month(self):
        from apps.annotation.utils import calculate_study_duration_months

        assert calculate_study_duration_months("2020-01", "2020-02") == 1.0

    def test_twelve_months(self):
        from apps.annotation.utils import calculate_study_duration_months

        assert calculate_study_duration_months("2020-01", "2021-01") == 12.0

    def test_partial_months(self):
        from apps.annotation.utils import calculate_study_duration_months

        assert calculate_study_duration_months("2020-06-15", "2021-03-10") == 8.0

    def test_year_only(self):
        from apps.annotation.utils import calculate_study_duration_months

        assert calculate_study_duration_months("2020", "2021") == 12.0

    def test_invalid_date_format(self):
        from apps.annotation.utils import calculate_study_duration_months

        assert calculate_study_duration_months("invalid", "2020-01") == 0.0

    def test_missing_start(self):
        from apps.annotation.utils import calculate_study_duration_months

        assert calculate_study_duration_months("", "2020-01") == 0.0

    def test_missing_end(self):
        from apps.annotation.utils import calculate_study_duration_months

        assert calculate_study_duration_months("2020-01", "") == 0.0

    def test_both_missing(self):
        from apps.annotation.utils import calculate_study_duration_months

        assert calculate_study_duration_months("", "") == 0.0

    def test_negative_duration_returns_zero(self):
        from apps.annotation.utils import calculate_study_duration_months

        assert calculate_study_duration_months("2021-01", "2020-01") == 0.0

    def test_exact_day_boundary(self):
        from apps.annotation.utils import calculate_study_duration_months

        # Same day of month should not subtract
        assert calculate_study_duration_months("2020-01-15", "2021-01-15") == 12.0

    def test_day_boundary_subtracts(self):
        from apps.annotation.utils import calculate_study_duration_months

        # End day < start day should subtract
        assert calculate_study_duration_months("2020-01-31", "2020-02-15") == 0.0


class TestGetGeographicContext:
    """Test the get_geographic_context function."""

    def test_no_api_key_returns_empty(self):
        from apps.annotation.utils import get_geographic_context

        result = get_geographic_context(40.7128, -74.0060)
        assert result == {
            "study_country": "",
            "study_state_or_province": "",
            "nearest_named_location": "",
            "error": "GeoNames is not configured.",
        }

    def test_with_api_key_calls_geonames(self):
        from apps.annotation.utils import get_geographic_context

        with patch("apps.annotation.utils._reverse_geocode_geonames") as mock:
            mock.return_value = {
                "study_country": "United States",
                "study_state_or_province": "New York",
                "nearest_named_location": "New York, United States",
            }
            result = get_geographic_context(40.7128, -74.0060, "test-user")
            assert result == {
                "study_country": "United States",
                "study_state_or_province": "New York",
                "nearest_named_location": "New York, United States",
            }

            mock.assert_called_once_with(40.7128, -74.0060, "test-user")


class TestReverseGeocodeGeoNames:
    """Test the _reverse_geocode_geonames function."""

    def test_successful_lookup(self):
        from apps.annotation.utils import _reverse_geocode_geonames

        mock_data = {
            "countryName": "United States",
            "adminName1": "California",
            "name": "San Francisco",
        }

        with patch("requests.get") as mock_get:
            mock_response = mock_get.return_value
            mock_response.json.return_value = mock_data
            mock_response.raise_for_status.return_value = None

            result = _reverse_geocode_geonames(37.7749, -122.4194, "test-username")

            assert result == {
                "study_country": "United States",
                "study_state_or_province": "California",
                "nearest_named_location": "San Francisco, United States",
            }

            mock_get.assert_called_once()
            args, kwargs = mock_get.call_args
            assert kwargs["params"]["lat"] == 37.7749
            assert kwargs["params"]["lng"] == -122.4194
            assert kwargs["params"]["username"] == "test-username"

    def test_no_admin1_code_uses_admin1Code(self):
        from apps.annotation.utils import _reverse_geocode_geonames

        mock_data = {
            "countryName": "United States",
            "admin1Code": "CA",
            "name": "San Francisco",
        }

        with patch("requests.get") as mock_get:
            mock_response = mock_get.return_value
            mock_response.json.return_value = mock_data
            mock_response.raise_for_status.return_value = None

            result = _reverse_geocode_geonames(37.7749, -122.4194, "test-username")

            assert result == {
                "study_country": "United States",
                "study_state_or_province": "CA",
                "nearest_named_location": "San Francisco, United States",
            }

    def test_geonames_status_error_is_surfaced_not_silently_blanked(self):
        """GeoNames returns HTTP 200 with a `status` error object for a bad or
        unregistered username, an unactivated reverse-geocoding service, or an
        exceeded hourly quota — it does not use a non-2xx HTTP status, so
        `response.raise_for_status()` can't catch it. Previously this silently
        produced an all-empty "successful" result with no way to tell the
        annotator why nothing was filled in."""
        from apps.annotation.utils import _reverse_geocode_geonames

        mock_data = {
            "status": {"message": "user does not exist", "value": 10},
        }

        with patch("requests.get") as mock_get:
            mock_response = mock_get.return_value
            mock_response.json.return_value = mock_data
            mock_response.raise_for_status.return_value = None

            result = _reverse_geocode_geonames(37.7749, -122.4194, "bad-username")

            assert result["study_country"] == ""
            assert result["study_state_or_province"] == ""
            assert result["error"] == "user does not exist"

    def test_no_country_name_in_response_is_surfaced_as_error(self):
        """A 200 response with no countryName (e.g. no match for these
        coordinates) must not be reported as a successful lookup either."""
        from apps.annotation.utils import _reverse_geocode_geonames

        with patch("requests.get") as mock_get:
            mock_response = mock_get.return_value
            mock_response.json.return_value = {}
            mock_response.raise_for_status.return_value = None

            result = _reverse_geocode_geonames(0.0, 0.0, "test-username")

            assert result["study_country"] == ""
            assert "error" in result
