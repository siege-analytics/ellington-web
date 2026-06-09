# Django functionality imports

from django.conf import settings
from locations.models import *

# Django models imports

from locations.models import *

DATA_TYPES_TO_PATH = {
    "VECTOR": settings.VECTOR_SPATIAL_DATA_SUBDIRECTORY,
    "RASTER": settings.RASTER_SPATIAL_DATA_SUBDIRECTORY,
    "TABULAR": settings.TABULAR_DATA_SUBDIRECTORY,
    "POINTCLOUD": settings.POINTCLOUD_SPATIAL_DATA_SUBDIRECTORY,
}


GADM_MODEL_FIELD_NAMES = [
    "GID_0",
    "GID_1",
    "GID_2",
    "GID_3",
    "GID_4",
    "GID_5",
]

GADM_MODEL_NAMES = [
    Admin_Level_0,
    Admin_Level_1,
    Admin_Level_2,
    Admin_Level_3,
    Admin_Level_4,
    Admin_Level_5,
]

CENSUS_TIGER_LINE_FIELD_NAMES = [
    "census_blockgroup",
    "census_cd",
    "census_county",
    "census_sldl",
    "census_sldu",
    "census_state",
    "census_tabblock",
    "census_tract",
    "census_ttract",
]

CENSUS_TIGER_LINE_MODEL_NAMES = [
    United_States_Census_Block_Group,
    United_States_Census_Congressional_District,
    United_States_Census_County,
    United_States_Census_State_Legislative_District_Lower,
    United_States_Census_State_Legislative_District_Upper,
    United_States_Census_State,
    United_States_Census_Tabulation_Block,
    United_States_Census_Tract,
    United_States_Census_Tribal_Tract,
]

LOCATION_MODEL_FIELDS_AND_NAMES_TO_TEST = {"timezone": Timezone}

GADM_MODEL_FIELD_NAMES_AND_MODEL_NAMES = {
    GADM_MODEL_FIELD_NAMES[i].lower(): GADM_MODEL_NAMES[i]
    for i in range(len(GADM_MODEL_FIELD_NAMES))
}

CENSUS_TIGER_LINE_FIELD_NAMES_AND_MODEL_NAMES = {
    CENSUS_TIGER_LINE_FIELD_NAMES[i].lower(): CENSUS_TIGER_LINE_MODEL_NAMES[i]
    for i in range(len(CENSUS_TIGER_LINE_FIELD_NAMES))
}


MODEL_FIELDS_AND_NAMES_TO_TEST = {}
MODEL_FIELDS_AND_NAMES_TO_TEST.update(GADM_MODEL_FIELD_NAMES_AND_MODEL_NAMES)
MODEL_FIELDS_AND_NAMES_TO_TEST.update(LOCATION_MODEL_FIELDS_AND_NAMES_TO_TEST)
MODEL_FIELDS_AND_NAMES_TO_TEST.update(CENSUS_TIGER_LINE_FIELD_NAMES_AND_MODEL_NAMES)

DOWNLOADS_DISPATCHER = {
    "gadm": {
        "url": "https://geodata.ucdavis.edu/gadm/gadm4.1/gadm_410-levels.zip",
        "model_to_model": [
            {Admin_Level_0: admin_level_0_mapping},
            {Admin_Level_1: admin_level_1_mapping},
            {Admin_Level_2: admin_level_2_mapping},
            {Admin_Level_3: admin_level_3_mapping},
            {Admin_Level_4: admin_level_4_mapping},
            {Admin_Level_5: admin_level_5_mapping},
        ],
        "type": "VECTOR",
        "unzipped_file_path": settings.VECTOR_SPATIAL_DATA_SUBDIRECTORY
        / "gadm_410-levels"
        / "gadm_410-levels.gpkg",
    },
    "timezone": {
        "url": "https://github.com/evansiroky/timezone-boundary-builder/releases/download/2024a/timezones-with-oceans-now.shapefile.zip",
        "model_to_model": [
            {Timezone: timezone_mapping},
        ],
        "type": "VECTOR",
        "unzipped_file_path": settings.VECTOR_SPATIAL_DATA_SUBDIRECTORY
        / "timezones-with-oceans-now.shapefile "
        / "combined-shapefile-with-oceans-now.shp",
    },
}
