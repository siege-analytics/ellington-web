from locations.models import *
from locations.serializers import *

from django.http import Http404
from rest_framework.views import APIView
from rest_framework.response import Response

from rest_framework import generics

# pagination

from rest_framework_gis.pagination import GeoJsonPagination

# Create your views here.

# AL0


class Admin_Level_0_List(generics.ListAPIView):
    queryset = Admin_Level_0.objects.all()
    serializer_class = Admin_Level_0_Serializer
    pagination_class = GeoJsonPagination


class Admin_Level_0_Detail(generics.RetrieveAPIView):
    queryset = Admin_Level_0.objects.all()
    serializer_class = Admin_Level_0_Serializer


# AL1


class Admin_Level_1_List(generics.ListAPIView):
    queryset = Admin_Level_1.objects.all()
    serializer_class = Admin_Level_1_Serializer
    pagination_class = GeoJsonPagination


class Admin_Level_1_Detail(generics.RetrieveAPIView):
    queryset = Admin_Level_1.objects.all()
    serializer_class = Admin_Level_1_Serializer


# Al2


class Admin_Level_2_List(generics.ListAPIView):
    queryset = Admin_Level_2.objects.all()
    serializer_class = Admin_Level_2_Serializer
    pagination_class = GeoJsonPagination


class Admin_Level_2_Detail(generics.RetrieveAPIView):
    queryset = Admin_Level_2.objects.all()
    serializer_class = Admin_Level_2_Serializer


# AL3


class Admin_Level_3_List(generics.ListAPIView):
    queryset = Admin_Level_3.objects.all()
    serializer_class = Admin_Level_3_Serializer
    pagination_class = GeoJsonPagination


class Admin_Level_3_Detail(generics.RetrieveAPIView):
    queryset = Admin_Level_3.objects.all()
    serializer_class = Admin_Level_3_Serializer


# AL4


class Admin_Level_4_List(generics.ListAPIView):
    queryset = Admin_Level_4.objects.all()
    serializer_class = Admin_Level_4_Serializer
    pagination_class = GeoJsonPagination


class Admin_Level_4_Detail(generics.RetrieveAPIView):
    queryset = Admin_Level_4.objects.all()
    serializer_class = Admin_Level_4_Serializer


# AL5


class Admin_Level_5_List(generics.ListAPIView):
    queryset = Admin_Level_5.objects.all()
    serializer_class = Admin_Level_5_Serializer
    pagination_class = GeoJsonPagination


class Admin_Level_5_Detail(generics.RetrieveAPIView):
    queryset = Admin_Level_5.objects.all()
    serializer_class = Admin_Level_5_Serializer
