# This is an auto-generated Django model module created by ogrinspect.
from django.contrib.gis.db import models


class United_States_Census_Tabulation_Block(models.Model):
    statefp20 = models.CharField(max_length=2)
    countyfp20 = models.CharField(max_length=3)
    tractce20 = models.CharField(max_length=6)
    blockce20 = models.CharField(max_length=4)
    geoid20 = models.CharField(max_length=15)
    geoidfq20 = models.CharField(max_length=24)
    name20 = models.CharField(max_length=10)
    mtfcc20 = models.CharField(max_length=5)
    ur20 = models.CharField(max_length=1)
    uace20 = models.CharField(max_length=5)
    funcstat20 = models.CharField(max_length=1)
    aland20 = models.BigIntegerField()
    awater20 = models.BigIntegerField()
    intptlat20 = models.CharField(max_length=11)
    intptlon20 = models.CharField(max_length=12)
    housing20 = models.BigIntegerField()
    pop20 = models.BigIntegerField()

    # geom fields

    geom = models.MultiPolygonField(srid=4269)

    # year
    year = models.IntegerField()

    # representative string

    def __str__(self):
        representative_string = self.namelsad
        return representative_string


# Auto-generated `LayerMapping` dictionary for United_States_Census_Tabulation_Block model
united_states_census_tabulation_block_mapping = {
    "statefp20": "STATEFP20",
    "countyfp20": "COUNTYFP20",
    "tractce20": "TRACTCE20",
    "blockce20": "BLOCKCE20",
    "geoid20": "GEOID20",
    "geoidfq20": "GEOIDFQ20",
    "name20": "NAME20",
    "mtfcc20": "MTFCC20",
    "ur20": "UR20",
    "uace20": "UACE20",
    "funcstat20": "FUNCSTAT20",
    "aland20": "ALAND20",
    "awater20": "AWATER20",
    "intptlat20": "INTPTLAT20",
    "intptlon20": "INTPTLON20",
    "housing20": "HOUSING20",
    "pop20": "POP20",
    "geom": "MULTIPOLYGON",
}
