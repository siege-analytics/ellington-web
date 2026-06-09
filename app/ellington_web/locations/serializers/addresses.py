from rest_framework import serializers
from locations.models import *
from rest_framework_gis.serializers import GeoFeatureModelSerializer


class United_States_AddressSerializer(GeoFeatureModelSerializer):
    class Meta:
        model = United_States_Address
        geo_field = "geom"
        fields = "__all__"
