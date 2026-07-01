"""
Utility functions for annotation features.

This module provides helper functions for:
- Geographic lookups (country/state from coordinates)
- Study duration calculation
"""

from datetime import datetime


def calculate_study_duration_months(start_date: str, end_date: str) -> float:
    """
    Calculate duration in months between two dates.

    Accepts ISO 8601 formats (YYYY, YYYY-MM, YYYY-MM-DD).

    Returns:
        Duration in months as a float. Returns 0.0 if dates are invalid or missing.

    Examples:
        >>> calculate_study_duration_months("2020-01", "2021-01")
        12.0
        >>> calculate_study_duration_months("2020-06-15", "2021-03-10")
        8.0
    """

    def parse_date(date_str: str) -> datetime | None:
        """Parse partial ISO dates."""
        if not date_str:
            return None
        try:
            if len(date_str) == 4:  # YYYY
                return datetime.strptime(date_str, "%Y")
            elif len(date_str) == 7:  # YYYY-MM
                return datetime.strptime(date_str, "%Y-%m")
            elif len(date_str) == 10:  # YYYY-MM-DD
                return datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return None
        return None

    start = parse_date(start_date)
    end = parse_date(end_date)

    if not start or not end:
        return 0.0

    # Calculate month difference
    months = (end.year - start.year) * 12 + (end.month - start.month)

    # Adjust for day difference
    if end.day < start.day:
        months -= 1

    return float(max(0, months))


def get_geographic_context(
    latitude: float, longitude: float, geonames_username: str | None = None
) -> dict:
    """
    Look up country and province from coordinates.

    Two approaches supported:
    1. GeoNames API (requires API key in geonames_username)
    2. Fallback to empty values (for when no API is available)

    Args:
        latitude: Latitude in decimal degrees (WGS 84)
        longitude: Longitude in decimal degrees (WGS 84)
        geonames_username: Optional GeoNames username for API lookup

    Returns:
        Dictionary with:
            - study_country: Country name
            - study_state_or_province: State/province name
            - nearest_named_location: City/town name
    """
    if geonames_username:
        return _reverse_geocode_geonames(latitude, longitude, geonames_username)
    else:
        # Return empty values - user can fill in manually or set up GeoNames API
        return {
            "study_country": "",
            "study_state_or_province": "",
            "nearest_named_location": "",
        }


def _reverse_geocode_geonames(latitude: float, longitude: float, username: str) -> dict:
    """
    Use GeoNames API to look up place names from coordinates.

    Args:
        latitude: Latitude in decimal degrees (WGS 84)
        longitude: Longitude in decimal degrees (WGS 84)
        username: GeoNames username for API access

    Returns:
        Dictionary with country, state, and nearest location name
    """
    import requests

    url = "http://api.geonames.org/reverseJSON"
    params = {"lat": latitude, "lng": longitude, "username": username, "style": "full"}

    try:
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()

        return {
            "study_country": data.get("countryName", ""),
            "study_state_or_province": data.get(
                "adminName1", data.get("admin1Code", "")
            ),
            "nearest_named_location": f"{data.get('name', '')}, {data.get('countryName', '')}",
        }
    except requests.exceptions.RequestException as e:
        print(f"GeoNames lookup failed: {e}")
        return {
            "study_country": "",
            "study_state_or_province": "",
            "nearest_named_location": "",
        }
