# This is an auto-generated Django model module created by ogrinspect.
from django.contrib.gis.db import models


class United_States_Census_Congressional_District(models.Model):
    statefp = models.CharField(max_length=2)
    cd118fp = models.CharField(max_length=2)
    geoid = models.CharField(max_length=4)
    geoidfq = models.CharField(max_length=13)
    namelsad = models.CharField(max_length=41)
    lsad = models.CharField(max_length=2)
    cdsessn = models.CharField(max_length=3)
    mtfcc = models.CharField(max_length=5)
    funcstat = models.CharField(max_length=1)
    aland = models.BigIntegerField()
    awater = models.BigIntegerField()
    intptlat = models.CharField(max_length=11)
    intptlon = models.CharField(max_length=12)

    # Geometry field

    geom = models.PolygonField(srid=4269)

    # year
    year = models.IntegerField()

    # representative string

    def __str__(self):
        representative_string = self.namelsad
        return representative_string


# Auto-generated `LayerMapping` dictionary for United_States_Congressional_District model
united_states_census_congressional_district_mapping = {
    "statefp": "STATEFP",
    "cd118fp": "CD118FP",
    "geoid": "GEOID",
    "geoidfq": "GEOIDFQ",
    "namelsad": "NAMELSAD",
    "lsad": "LSAD",
    "cdsessn": "CDSESSN",
    "mtfcc": "MTFCC",
    "funcstat": "FUNCSTAT",
    "aland": "ALAND",
    "awater": "AWATER",
    "intptlat": "INTPTLAT",
    "intptlon": "INTPTLON",
    "geom": "POLYGON",
}
