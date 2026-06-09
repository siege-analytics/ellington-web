from rest_framework_gis.serializers import GeoFeatureModelSerializer
from locations.models import *
from rest_framework import serializers


class Admin_Level_0_Serializer(GeoFeatureModelSerializer):
    class Meta:
        model = Admin_Level_0
        geo_field = "geom"
        # fields = [f.name for f in Admin_Level_0._meta.local_fields]
        fields = [
            "id",
            "gid_0",
            "country",
        ]


class Admin_Level_1_Serializer(GeoFeatureModelSerializer):
    class Meta:
        model = Admin_Level_1
        geo_field = "geom"

        # foreign keys
        gid_0 = serializers.HyperlinkedRelatedField(
            view_name="admin_level_0_detail", many=False, read_only=True
        )

        # fields
        # fields = [f.name for f in Admin_Level_1._meta.local_fields]
        fields = [
            "id",
            "gid_0",
            "country",
            "gid_1",
            "name_1",
            "varname_1",
            "nl_name_1",
            "type_1",
            "engtype_1",
            "cc_1",
            "hasc_1",
            "iso_1",
        ]


class Admin_Level_2_Serializer(GeoFeatureModelSerializer):
    class Meta:
        model = Admin_Level_2
        geo_field = "geom"

        # foreign keys
        gid_0 = serializers.HyperlinkedRelatedField(
            view_name="admin_level_0_detail", many=False, read_only=True
        )
        gid_1 = serializers.HyperlinkedRelatedField(
            view_name="admin_level_1_detail", many=False, read_only=True
        )

        # fields
        # fields = [f.name for f in Admin_Level_2._meta.local_fields]
        fields = [
            "id",
            "gid_0",
            "country",
            "gid_1",
            "name_1",
            "nl_name_1",
            "gid_2",
            "name_2",
            "varname_2",
            "nl_name_2",
            "type_2",
            "engtype_2",
            "cc_2",
            "hasc_2",
        ]


class Admin_Level_3_Serializer(GeoFeatureModelSerializer):
    class Meta:
        model = Admin_Level_3
        geo_field = "geom"

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

        # fields
        # fields = [f.name for f in Admin_Level_3._meta.local_fields]
        fields = [
            "id",
            "gid_0",
            "country",
            "gid_1",
            "name_1",
            "nl_name_1",
            "gid_2",
            "name_2",
            "nl_name_2",
            "gid_3",
            "name_3",
            "varname_3",
            "nl_name_3",
            "type_3",
            "engtype_3",
            "cc_3",
            "hasc_3",
        ]


class Admin_Level_4_Serializer(GeoFeatureModelSerializer):
    class Meta:
        model = Admin_Level_4
        geo_field = "geom"

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

        # fields

        # fields = [f.name for f in Admin_Level_4._meta.local_fields]
        fields = [
            "id",
            "gid_0",
            "country",
            "gid_1",
            "name_1",
            "gid_2",
            "name_2",
            "gid_3",
            "name_3",
            "gid_4",
            "name_4",
            "varname_4",
            "type_4",
            "engtype_4",
            "cc_4",
        ]


class Admin_Level_5_Serializer(GeoFeatureModelSerializer):
    class Meta:
        model = Admin_Level_5
        geo_field = "geom"

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

        # fields
        # fields = [f.name for f in Admin_Level_5._meta.local_fields]
        fields = [
            "id",
            "gid_0",
            "country",
            "gid_1",
            "name_1",
            "gid_2",
            "name_2",
            "gid_3",
            "name_3",
            "gid_4",
            "name_4",
            "gid_5",
            "name_5",
            "type_5",
            "engtype_5",
            "cc_5",
        ]
