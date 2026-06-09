"""
GST-specific geocoding wrappers.

These are wrappers around siege_utilities.geo.geocoding.use_nominatim_geocoder
(or geopy directly) that match GST's pre-SU calling shape. The plan is to
port these up to SU eventually (siege_utilities#515); until then they live
here so consumers don't need to be rewritten when SU absorbs them.
"""

import logging
import math

from django.conf import settings
from geopy import geocoders

logger = logging.getLogger("django")


def distance_to_decimal_degrees(distance, latitude):
    """
    Convert a distance (django.contrib.gis.measure.Distance) to decimal degrees
    longitudinally at a given latitude.

    Source: https://en.wikipedia.org/wiki/Decimal_degrees
    1 longitudinal degree at the equator = 111,319.5 m
    """
    lat_radians = latitude * (math.pi / 180)
    return distance.m / (111_319.5 * math.cos(lat_radians))


def geocode_with_nominatim_public(concatenated_address):
    """Geocode a single address via Nominatim public endpoint."""
    try:
        geocoder = geocoders.Nominatim(user_agent=settings.NOMINATIM_USER_AGENT)
        result = geocoder.geocode(concatenated_address, addressdetails=True)
        address_information = result.raw
        logger.info(f"Successfully geocoded {concatenated_address}")
        return address_information
    except Exception as e:
        logger.error(f"There was an error geocoding {concatenated_address}: {e}")
        return False
