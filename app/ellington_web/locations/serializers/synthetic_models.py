from rest_framework import serializers
from locations.models import *
from rest_framework_gis.serializers import GeoFeatureModelSerializer

from .addresses import United_States_AddressSerializer

LOCATION_FIELDS = [
    "id",
    "name",
    "nickname",
    "address",
    "timezone",
    "gid_0",
    "gid_1",
    "gid_2",
    "gid_3",
    "gid_4",
    "gid_5",
]


class Place_Serializer(GeoFeatureModelSerializer):

    address = United_States_AddressSerializer(many=False, read_only=True)

    timezone = serializers.HyperlinkedRelatedField(
        view_name="timezone_detail", many=False, read_only=True
    )
    gid_0 = serializers.HyperlinkedRelatedField(
        view_name="admin_level_0_detail", many=False, read_only=True
    )
    gid_1 = serializers.HyperlinkedRelatedField(
        view_name="admin_level_1_detail", many=False, read_only=True
    )
    gid_2 = serializers.HyperlinkedRelatedField(
        view_name="admin_level_2_detail", many=False, read_only=True
    )
    gid_3 = serializers.HyperlinkedRelatedField(
        view_name="admin_level_3_detail", many=False, read_only=True
    )
    gid_4 = serializers.HyperlinkedRelatedField(
        view_name="admin_level_4_detail", many=False, read_only=True
    )
    gid_5 = serializers.HyperlinkedRelatedField(
        view_name="admin_level_5_detail", many=False, read_only=True
    )

    class Meta:
        model = Place
        geo_field = "geom"
        # fields = "__all__"
        fields = LOCATION_FIELDS
        depth = 1


class LocalitySerializer(GeoFeatureModelSerializer):
    class Meta:
        model = Locality

        # foreign keys

        gid_0 = serializers.HyperlinkedRelatedField(
            view_name="admin_level_0_detail", many=False, read_only=True
        )
        gid_1 = serializers.HyperlinkedRelatedField(
            view_name="admin_level_1_detail", many=False, read_only=True
        )
        gid_2 = serializers.HyperlinkedRelatedField(
            view_name="admin_level_2_detail", many=False, read_only=True
        )
        gid_3 = serializers.HyperlinkedRelatedField(
            view_name="admin_level_3_detail", many=False, read_only=True
        )
        gid_4 = serializers.HyperlinkedRelatedField(
            view_name="admin_level_4_detail", many=False, read_only=True
        )
        gid_5 = serializers.HyperlinkedRelatedField(
            view_name="admin_level_5_detail", many=False, read_only=True
        )
        timezone = serializers.HyperlinkedRelatedField(
            view_name="timezone_detail", many=False, read_only=True
        )

        geo_field = "geom"
        fields = LOCATION_FIELDS
