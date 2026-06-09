from django.urls import path
from rest_framework.routers import format_suffix_patterns
from locations import views


urlpatterns = []

# There are a lot of URLs, so we're going to separate them into separate lists and then flatten into one.

gadm = [
    # AL0
    path(
        "admin_level_0s/", views.Admin_Level_0_List.as_view(), name="admin_level_0_list"
    ),
    path(
        "admin_level_0s/<int:pk>/",
        views.Admin_Level_0_Detail.as_view(),
        name="admin_level_0_detail",
    ),
    # AL1
    path(
        "admin_level_1s/", views.Admin_Level_1_List.as_view(), name="admin_level_1_list"
    ),
    path(
        "admin_level_1s/<int:pk>/",
        views.Admin_Level_1_Detail.as_view(),
        name="admin_level_1_detail",
    ),
    # AL2
    path(
        "admin_level_2s/",
        views.Admin_Level_2_List.as_view(),
        name="admin_level_2_list",
    ),
    path(
        "admin_level_2s/<int:pk>/",
        views.Admin_Level_2_Detail.as_view(),
        name="admin_level_2_detail",
    ),
    # AL3
    path(
        "admin_level_3s/",
        views.Admin_Level_3_List.as_view(),
        name="admin_level_3_list",
    ),
    path(
        "admin_level_3s/<int:pk>/",
        views.Admin_Level_3_Detail.as_view(),
        name="admin_level_3_detail",
    ),
    # AL4
    path(
        "admin_level_4s/",
        views.Admin_Level_4_List.as_view(),
        name="admin_level_4_list",
    ),
    path(
        "admin_level_4s/<int:pk>/",
        views.Admin_Level_4_Detail.as_view(),
        name="admin_level_4_detail",
    ),
    # AL5
    path(
        "admin_level_5s/",
        views.Admin_Level_5_List.as_view(),
        name="admin_level_5_list",
    ),
    path(
        "admin_level_5s/<int:pk>/",
        views.Admin_Level_5_Detail.as_view(),
        name="admin_level_5_detail",
    ),
]

time = [
    path("timezones/", views.Timezone_List.as_view(), name="timezone_list"),
    path(
        "timezones/<int:pk>/",
        views.Timezone_Detail.as_view(),
        name="timezone_detail",
    ),
]

addresses = [
    path(
        "united_states_addresses",
        views.United_States_Address_List.as_view(),
        name="us_address_list",
    ),
    path(
        "united_states_addresses",
        views.United_States_Address_Detail.as_view(),
        name="us_address_detail",
    ),
]

synthetics = [
    path("places/", views.PlaceList.as_view(), name="places_list"),
    path("places/<int:pk>/", views.PlaceDetail.as_view(), name="places_detail"),
    path("places/lookup/", views.Filtered_Place_List.as_view(), name="lookup"),
]

# this is licit
# new_urls = []
#
urlpatterns.extend(gadm)
urlpatterns.extend(time)
urlpatterns.extend(synthetics)
urlpatterns.extend(addresses)

urlpatterns = format_suffix_patterns(urlpatterns)
