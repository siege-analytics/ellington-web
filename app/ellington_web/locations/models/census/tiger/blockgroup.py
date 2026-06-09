# This is an auto-generated Django model module created by ogrinspect.
from django.contrib.gis.db import models


class United_States_Census_Block_Group(models.Model):

    # given fields
    statefp = models.CharField(max_length=2)
    countyfp = models.CharField(max_length=3)
    tractce = models.CharField(max_length=6)
    blkgrpce = models.CharField(max_length=1)
    geoid = models.CharField(max_length=12)
    geoidfq = models.CharField(max_length=21)
    namelsad = models.CharField(max_length=13)
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

    def __str__(self):
        representative_string = self.namelsad
        return representative_string


# Auto-generated `LayerMapping` dictionary for US_Census_Block_Group model
# united_states_census_block_group_mapping = {
#     "statefp": "STATEFP",
#     "countyfp": "COUNTYFP",
#     "tractce": "TRACTCE",
#     "blkgrpce": "BLKGRPCE",
#     "geoid": "GEOID",
#     "geoidfq": "GEOIDFQ",
#     "namelsad": "NAMELSAD",
#     "mtfcc": "MTFCC",
#     "funcstat": "FUNCSTAT",
#     "aland": "ALAND",
#     "awater": "AWATER",
#     "intptlat": "INTPTLAT",
#     "intptlon": "INTPTLON",
#     "geom": "POLYGON",
# }
