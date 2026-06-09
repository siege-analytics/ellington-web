from django.contrib.gis.db import models


class United_States_Census_County(models.Model):
    statefp = models.CharField(max_length=2)
    countyfp = models.CharField(max_length=3)
    countyns = models.CharField(max_length=8)
    geoid = models.CharField(max_length=5)
    geoidfq = models.CharField(max_length=14)
    name = models.CharField(max_length=100)
    namelsad = models.CharField(max_length=100)
    lsad = models.CharField(max_length=2)
    classfp = models.CharField(max_length=2)
    mtfcc = models.CharField(max_length=5)
    csafp = models.CharField(max_length=3)
    cbsafp = models.CharField(max_length=5)
    metdivfp = models.CharField(max_length=5)
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


# Auto-generated `LayerMapping` dictionary for United_States_Census_County model
united_states_census_county_mapping = {
    "statefp": "STATEFP",
    "countyfp": "COUNTYFP",
    "countyns": "COUNTYNS",
    "geoid": "GEOID",
    "geoidfq": "GEOIDFQ",
    "name": "NAME",
    "namelsad": "NAMELSAD",
    "lsad": "LSAD",
    "classfp": "CLASSFP",
    "mtfcc": "MTFCC",
    "csafp": "CSAFP",
    "cbsafp": "CBSAFP",
    "metdivfp": "METDIVFP",
    "funcstat": "FUNCSTAT",
    "aland": "ALAND",
    "awater": "AWATER",
    "intptlat": "INTPTLAT",
    "intptlon": "INTPTLON",
    "geom": "MULTIPOLYGON",
}
