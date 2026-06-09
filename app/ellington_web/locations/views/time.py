from locations.models import *
from locations.serializers import *

from django.http import Http404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import generics


from rest_framework_gis.pagination import GeoJsonPagination

import logging

logger = logging.getLogger("django")

# Create your views here.

# Timezone


class Timezone_List(generics.ListAPIView):

    queryset = Timezone.objects.all().order_by("pk")
    serializer_class = Timezone_Serializer


class Timezone_Detail(generics.RetrieveAPIView):
    queryset = Timezone.objects.all()
    serializer_class = Timezone_Serializer
