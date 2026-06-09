from locations.models import *
from locations.serializers import *

from rest_framework.response import Response
from rest_framework import generics

from rest_framework_gis.pagination import GeoJsonPagination

# logging

import logging

logger = logging.getLogger("django")


# Create your views here.
class PlaceList(generics.ListAPIView):
    queryset = Place.objects.all()
    serializer_class = Place_Serializer


class PlaceDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Place.objects.all()
    serializer_class = Place_Serializer
