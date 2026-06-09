from rest_framework_gis.serializers import GeoFeatureModelSerializer
from locations.models import *


class Timezone_Serializer(GeoFeatureModelSerializer):
    class Meta:
        model = Timezone
        geo_field = "geom"
        fields = [
            "pk",
            "tzid",
        ]
