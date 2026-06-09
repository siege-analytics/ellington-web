# Models and serializers
from locations.models import *
from locations.serializers import *

# DRF
from rest_framework import generics
from django.conf import settings

# DRF GIS
from rest_framework_gis.pagination import GeoJsonPagination


# geography things
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import Distance
from django.contrib.gis.db.models.functions import Transform

# logging

import logging

logger = logging.getLogger("django")


# Create your views here.
class Filtered_Place_List(generics.ListAPIView):

    # serializer for filtered results
    serializer_class = Place_Serializer
    pagination_class = GeoJsonPagination

    # override the queryset with a custom method using the params from URL

    def get_queryset(self):

        # get params from url
        # Assuming EPSG:4326
        try:
            longitude = float(self.request.query_params.get("longitude"))
            latitude = float(self.request.query_params.get("latitude"))
            radius = Distance(m=float(self.request.query_params.get("radius")))
            epsg = int(
                self.request.query_params.get(
                    "epsg", settings.DEFAULT_PROJECTION_NUMBER
                )
            )
            logging.info(f"Received params: {longitude}, {latitude}, {radius}, {epsg}")

            reference_geom = Point((longitude, latitude), srid=epsg)
            logging.info(f"Made reference geom: {reference_geom}")

            reference_geom.transform(
                settings.PREFERRED_PROJECTION_FOR_US_DISTANCE_SEARCH
            )
            logging.info(f"Reprojected reference point: {reference_geom.srid}")
            logging.info("About to start queryset")
            queryset = (
                Place.objects.annotate(
                    distance_geom=Transform(
                        "geom", settings.PREFERRED_PROJECTION_FOR_US_DISTANCE_SEARCH
                    )
                )
                .filter(distance_geom__dwithin=(reference_geom, radius))
                .order_by("pk")
            )
            logging.info(f"Queried queryset: {len(queryset)}")

            return queryset

        except Exception as e:
            message = ""
            message += f"There was an error getting the radius results for Place: {e}"
            logging.error(message)
            queryset = None

        return queryset
