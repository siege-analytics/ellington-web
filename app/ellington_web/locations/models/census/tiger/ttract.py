# This is an auto-generated Django model module created by ogrinspect.
from django.contrib.gis.db import models


class United_States_Census_Tribal_Tract(models.Model):
    region = models.CharField(max_length=2)
    division = models.CharField(max_length=2)
    statefp = models.CharField(max_length=2)
    statens = models.CharField(max_length=8)
    geoid = models.CharField(max_length=2)
    geoidfq = models.CharField(max_length=11)
    stusps = models.CharField(max_length=2)
    name = models.CharField(max_length=100)
    lsad = models.CharField(max_length=2)
    mtfcc = models.CharField(max_length=5)
    funcstat = models.CharField(max_length=1)
    aland = models.BigIntegerField()
    awater = models.BigIntegerField()
    intptlat = models.CharField(max_length=11)
    intptlon = models.CharField(max_length=12)
    geom = models.MultiPolygonField(srid=4269)


# Auto-generated `LayerMapping` dictionary for United_States_Tribal_Tract model
united_states_census_tribal_tract_mapping = {
    "region": "REGION",
    "division": "DIVISION",
    "statefp": "STATEFP",
    "statens": "STATENS",
    "geoid": "GEOID",
    "geoidfq": "GEOIDFQ",
    "stusps": "STUSPS",
    "name": "NAME",
    "lsad": "LSAD",
    "mtfcc": "MTFCC",
    "funcstat": "FUNCSTAT",
    "aland": "ALAND",
    "awater": "AWATER",
    "intptlat": "INTPTLAT",
    "intptlon": "INTPTLON",
    "geom": "MULTIPOLYGON",
}
