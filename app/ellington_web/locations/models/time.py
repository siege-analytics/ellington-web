from __future__ import unicode_literals
from django.contrib.gis.db import models
from postgres_copy import CopyManager


class Timezone(models.Model):
    tzid = models.CharField(max_length=80)

    # GeoDjango geometry
    geom = models.MultiPolygonField(srid=4326)

    # CopyManager

    objects = CopyManager()

    def __str__(self):
        representative_string = f"TZID: {self.tzid}"
        return representative_string


# Auto-generated `LayerMapping` dictionary for  Timezone model
timezone_mapping = {
    "tzid": "tzid",
    "geom": "MULTIPOLYGON",
}
