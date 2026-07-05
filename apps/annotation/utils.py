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

    If only the year is provided (e.g., "2023" and "2024"), the calculation
    assumes January of the start year and January of the end year.

    Returns:
        Duration in months as a float. Returns 0.0 if dates are invalid or missing.

    Examples:
        >>> calculate_study_duration_months("2020-01", "2021-01")
        12.0
        >>> calculate_study_duration_months("2020-06-15", "2021-03-10")
        8.0
        >>> calculate_study_duration_months("2023", "2024")
        12.0
    """

    def parse_date(date_str: str) -> datetime | None:
        """Parse partial ISO dates."""
        if not date_str:
            return None
        try:
            if len(date_str) == 4:  # YYYY
                return datetime.strptime(date_str + "-01-01", "%Y-%m-%d")
            elif len(date_str) == 7:  # YYYY-MM
                return datetime.strptime(date_str + "-01", "%Y-%m-%d")
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
            "error": "GeoNames is not configured.",
        }


_EMPTY_GEO_CONTEXT = {
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
        Dictionary with country, state, and nearest location name. Includes an
        "error" key (and otherwise-empty values) if the lookup didn't actually
        resolve a location — GeoNames returns HTTP 200 with a `status` error
        object (bad/unregistered username, hourly quota exceeded, etc.)
        rather than a non-2xx status, so `response.raise_for_status()` alone
        can't detect it; treating a 200 response with no countryName as
        success previously left the annotator staring at a "success" message
        with blank fields and no indication why.

    Note: GeoNames has no `reverseJSON` service (a prior version of this code
    called that path and always got a 404). `findNearbyPlaceNameJSON` is the
    real endpoint that returns country + admin1 (state/province) + nearest
    populated place in one call, nested under a `geonames` list. The `https`
    host must be `secure.geonames.org` — `api.geonames.org` doesn't serve a
    matching TLS certificate over https.
    """
    import requests

    url = "https://secure.geonames.org/findNearbyPlaceNameJSON"
    params = {"lat": latitude, "lng": longitude, "username": username, "style": "full"}

    try:
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        print(f"GeoNames lookup failed: {e}")
        return {**_EMPTY_GEO_CONTEXT, "error": f"GeoNames request failed: {e}"}

    status = data.get("status")
    if status:
        message = status.get("message", "GeoNames returned an error.")
        print(f"GeoNames lookup failed: {message}")
        return {**_EMPTY_GEO_CONTEXT, "error": message}

    matches = data.get("geonames") or []
    if not matches:
        return {
            **_EMPTY_GEO_CONTEXT,
            "error": "GeoNames found no location for these coordinates.",
        }

    place = matches[0]
    return {
        "study_country": place.get("countryName", ""),
        "study_state_or_province": place.get("adminName1", place.get("adminCode1", "")),
        "nearest_named_location": f"{place.get('name', '')}, {place.get('countryName', '')}",
    }
