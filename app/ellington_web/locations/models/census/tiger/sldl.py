from django.contrib.gis.db import models


class United_States_Census_State_Legislative_District_Lower(models.Model):
    statefp = models.CharField(max_length=2)
    sldlst = models.CharField(max_length=3)
    geoid = models.CharField(max_length=5)
    geoidfq = models.CharField(max_length=14)
    namelsad = models.CharField(max_length=100)
    lsad = models.CharField(max_length=2)
    lsy = models.CharField(max_length=4)
    mtfcc = models.CharField(max_length=5)
    funcstat = models.CharField(max_length=1)
    aland = models.BigIntegerField()
    awater = models.BigIntegerField()
    intptlat = models.CharField(max_length=11)
    intptlon = models.CharField(max_length=12)

    # Geometry fields

    geom = models.PolygonField(srid=4269)

    # year
    year = models.IntegerField()

    # representative string

    def __str__(self):
        representative_string = self.namelsad
        return representative_string


# Auto-generated `LayerMapping` dictionary for United_States_State_Legislative_District_Lower model
united_states_census_state_legislative_district_lower_mapping = {
    "statefp": "STATEFP",
    "sldlst": "SLDLST",
    "geoid": "GEOID",
    "geoidfq": "GEOIDFQ",
    "namelsad": "NAMELSAD",
    "lsad": "LSAD",
    "lsy": "LSY",
    "mtfcc": "MTFCC",
    "funcstat": "FUNCSTAT",
    "aland": "ALAND",
    "awater": "AWATER",
    "intptlat": "INTPTLAT",
    "intptlon": "INTPTLON",
    "geom": "POLYGON",
}
