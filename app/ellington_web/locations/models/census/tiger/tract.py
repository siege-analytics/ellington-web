# This is an auto-generated Django model module created by ogrinspect.
from django.contrib.gis.db import models


class United_States_Census_Tract(models.Model):
    statefp = models.CharField(max_length=2)
    countyfp = models.CharField(max_length=3)
    tractce = models.CharField(max_length=6)
    geoid = models.CharField(max_length=11)
    geoidfq = models.CharField(max_length=20)
    name = models.CharField(max_length=7)
    namelsad = models.CharField(max_length=20)
    mtfcc = models.CharField(max_length=5)
    funcstat = models.CharField(max_length=1)
    aland = models.BigIntegerField()
    awater = models.BigIntegerField()
    intptlat = models.CharField(max_length=11)
    intptlon = models.CharField(max_length=12)

    # geom fields

    geom = models.MultiPolygonField(srid=4269)

    # year
    year = models.IntegerField()

    # representative string

    def __str__(self):
        representative_string = self.namelsad
        return representative_string


# Auto-generated `LayerMapping` dictionary for United_States_Census_Tract model
united_states_census_tract_mapping = {
    "statefp": "STATEFP",
    "countyfp": "COUNTYFP",
    "tractce": "TRACTCE",
    "geoid": "GEOID",
    "geoidfq": "GEOIDFQ",
    "name": "NAME",
    "namelsad": "NAMELSAD",
    "mtfcc": "MTFCC",
    "funcstat": "FUNCSTAT",
    "aland": "ALAND",
    "awater": "AWATER",
    "intptlat": "INTPTLAT",
    "intptlon": "INTPTLON",
    "geom": "MULTIPOLYGON",
}
