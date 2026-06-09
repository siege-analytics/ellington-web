import pathlib


# going to build paths for use relative to the settings file

ALL_PARENTS = list(pathlib.Path(__file__).parents)

SETTINGS_DIRECTORY = ALL_PARENTS[0]             # directory that contains the settings file
DJANGO_APP_DIRECTORY = ALL_PARENTS[1]           # directory that contains the settings directory and manage.py
DJANGO_PROJECT_DIRECTORY = ALL_PARENTS[2]       # directory that contains all django apps
DOCKER_APP_DIRECTORY = ALL_PARENTS[3]           # directory on docker that contains code

# now build paths to useful directories

# Docker App Directory paths

SCRATCH_FILES_DIRECTORY = DOCKER_APP_DIRECTORY / 'scratch'
REFERENCES_DIRECTORY = DOCKER_APP_DIRECTORY / 'references'

# Data

DATA_DIRECTORY = DOCKER_APP_DIRECTORY / 'data'
SPATIAL_DATA_SUBDIRECTORY = DATA_DIRECTORY / 'spatial'
TABULAR_DATA_SUBDIRECTORY = DATA_DIRECTORY / 'tabular'
VECTOR_SPATIAL_DATA_SUBDIRECTORY = SPATIAL_DATA_SUBDIRECTORY / 'vector'
RASTER_SPATIAL_DATA_SUBDIRECTORY = SPATIAL_DATA_SUBDIRECTORY / 'raster'
POINTCLOUD_SPATIAL_DATA_SUBDIRECTORY = SPATIAL_DATA_SUBDIRECTORY / 'pointcloud'
CENSUS_TIGER_LINE_DATA = VECTOR_SPATIAL_DATA_SUBDIRECTORY / 'census_tiger'

# Logs

LOGS_DIRECTORY = DOCKER_APP_DIRECTORY / 'logs'

# Utilities have to be handled oddly because I'm trying to handle it with Pathlib
# and this is done with importlib

UTILITIES_PACKAGE_NAME='utilities'
PATH_TO_UTILITIES_PACKAGE=DJANGO_PROJECT_DIRECTORY / UTILITIES_PACKAGE_NAME

# Creating a collection for use in a management command to ensure that paths exist
# Every time I create a new path, I'm just going to add it here
# There's got to be a better way to do this

NECESSARY_PATHS = [
    SETTINGS_DIRECTORY,
    DJANGO_APP_DIRECTORY,
    DJANGO_PROJECT_DIRECTORY,
    DOCKER_APP_DIRECTORY,
    DATA_DIRECTORY,
    SPATIAL_DATA_SUBDIRECTORY,
    TABULAR_DATA_SUBDIRECTORY,
    VECTOR_SPATIAL_DATA_SUBDIRECTORY,
    RASTER_SPATIAL_DATA_SUBDIRECTORY,
    POINTCLOUD_SPATIAL_DATA_SUBDIRECTORY,
    CENSUS_TIGER_LINE_DATA,
    LOGS_DIRECTORY,
    UTILITIES_PACKAGE_NAME,
    PATH_TO_UTILITIES_PACKAGE,
    SCRATCH_FILES_DIRECTORY,
    REFERENCES_DIRECTORY,
]