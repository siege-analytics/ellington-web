from __future__ import unicode_literals
from django.contrib.gis.db import models

# putting layer mappings next to models for ease of reference
# For foreign keys we are going to use the gid field for the key


class Admin_Level_0(models.Model):
    # Admin Level 0

    # Regular Django fields
    gid_0 = models.CharField(max_length=250, null=True, blank=True, default=None)
    country = models.CharField(max_length=250, null=True, blank=True, default=None)

    # GeoDjango Geometry

    geom = models.MultiPolygonField(srid=4326, null=True, blank=True, default=None)

    # Returns the string representation of the model.
    def __str__(self):  # __unicode__ on Python 2
        representative_string = f"GID:{self.gid_0} Country:{self.country}"
        return representative_string

    class Meta:
        ordering = ["gid_0"]


# Auto-generated `LayerMapping` dictionary for Country model
admin_level_0_mapping = {
    "gid_0": "GID_0",
    "country": "COUNTRY",
    "geom": "MULTIPOLYGON",
}


class Admin_Level_1(models.Model):
    # Foreign keys (populated after parallel load)
    gid_0 = models.ForeignKey(
        Admin_Level_0, on_delete=models.SET_DEFAULT, null=True, blank=True, default=None
    )
    # String field for initial parallel load (before FK resolution)
    gid_0_string = models.CharField(max_length=250, null=True, blank=True, default=None,
                                     help_text="Temp field for parallel loading")
    
    country = models.CharField(max_length=250, null=True, blank=True, default=None)
    gid_1 = models.CharField(max_length=250, null=True, blank=True, default=None)
    name_1 = models.CharField(max_length=250, null=True, blank=True, default=None)
    varname_1 = models.CharField(max_length=250, null=True, blank=True, default=None)
    nl_name_1 = models.CharField(max_length=250, null=True, blank=True, default=None)
    type_1 = models.CharField(max_length=250, null=True, blank=True, default=None)
    engtype_1 = models.CharField(max_length=250, null=True, blank=True, default=None)
    cc_1 = models.CharField(max_length=250, null=True, blank=True, default=None)
    hasc_1 = models.CharField(max_length=250, null=True, blank=True, default=None)
    iso_1 = models.CharField(max_length=250, null=True, blank=True, default=None)

    # GeoDjango Geometry

    geom = models.MultiPolygonField(srid=4326)

    # returns string representation of model

    def __str__(self):
        representative_string = (
            f"GID:{self.gid_1}, Name 1: {self.name_1} Country:{self.country}"
        )
        return representative_string

    class Meta:
        ordering = ["gid_1"]


# https://stackoverflow.com/questions/21197483/geodjango-layermapping-foreign-key

# Auto-generated `LayerMapping` dictionary for Admin_Level_1 model
admin_level_1_mapping = {
    "gid_0": {"gid_0": "GID_0"},
    "country": "COUNTRY",
    "gid_1": "GID_1",
    "name_1": "NAME_1",
    "varname_1": "VARNAME_1",
    "nl_name_1": "NL_NAME_1",
    "type_1": "TYPE_1",
    "engtype_1": "ENGTYPE_1",
    "cc_1": "CC_1",
    "hasc_1": "HASC_1",
    "iso_1": "ISO_1",
    "geom": "MULTIPOLYGON",
}


class Admin_Level_2(models.Model):
    # Foreign keys (populated after parallel load)
    gid_0 = models.ForeignKey(
        Admin_Level_0, on_delete=models.SET_DEFAULT, null=True, blank=True, default=None
    )
    gid_0_string = models.CharField(max_length=250, null=True, blank=True, default=None,
                                     help_text="Temp field for parallel loading")
    
    country = models.CharField(max_length=250, null=True, blank=True, default=None)
    
    gid_1 = models.ForeignKey(
        Admin_Level_1, on_delete=models.SET_DEFAULT, null=True, blank=True, default=None
    )
    gid_1_string = models.CharField(max_length=250, null=True, blank=True, default=None,
                                     help_text="Temp field for parallel loading")
    
    name_1 = models.CharField(max_length=250, null=True, blank=True, default=None)
    nl_name_1 = models.CharField(max_length=250, null=True, blank=True, default=None)
    gid_2 = models.CharField(max_length=250, null=True, blank=True, default=None)
    name_2 = models.CharField(max_length=250, null=True, blank=True, default=None)
    varname_2 = models.CharField(max_length=250, null=True, blank=True, default=None)
    nl_name_2 = models.CharField(max_length=250, null=True, blank=True, default=None)
    type_2 = models.CharField(max_length=250, null=True, blank=True, default=None)
    engtype_2 = models.CharField(max_length=250, null=True, blank=True, default=None)
    cc_2 = models.CharField(max_length=250, null=True, blank=True, default=None)
    hasc_2 = models.CharField(max_length=250, null=True, blank=True, default=None)

    # GeoDjango Geometry
    geom = models.MultiPolygonField(srid=4326)

    def __str__(self):
        representative_string = (
            f"GID:{self.gid_2}, Name 2: {self.name_2} Country:{self.country}"
        )
        return representative_string

    class Meta:
        ordering = ["gid_2"]


# Auto-generated `LayerMapping` dictionary for Admin_Level_2 model
admin_level_2_mapping = {
    "gid_0": {"gid_0": "GID_0"},
    "country": "COUNTRY",
    "gid_1": {"gid_1": "GID_1"},
    "name_1": "NAME_1",
    "nl_name_1": "NL_NAME_1",
    "gid_2": "GID_2",
    "name_2": "NAME_2",
    "varname_2": "VARNAME_2",
    "nl_name_2": "NL_NAME_2",
    "type_2": "TYPE_2",
    "engtype_2": "ENGTYPE_2",
    "cc_2": "CC_2",
    "hasc_2": "HASC_2",
    "geom": "MULTIPOLYGON",
}


class Admin_Level_3(models.Model):
    # Foreign keys (populated after parallel load)
    gid_0 = models.ForeignKey(
        Admin_Level_0, on_delete=models.SET_DEFAULT, null=True, blank=True, default=None
    )
    gid_0_string = models.CharField(max_length=250, null=True, blank=True, default=None,
                                     help_text="Temp field for parallel loading")
    
    country = models.CharField(max_length=250, null=True, blank=True, default=None)
    
    gid_1 = models.ForeignKey(
        Admin_Level_1, on_delete=models.SET_DEFAULT, null=True, blank=True, default=None
    )
    gid_1_string = models.CharField(max_length=250, null=True, blank=True, default=None,
                                     help_text="Temp field for parallel loading")
    
    name_1 = models.CharField(max_length=250, null=True, blank=True, default=None)
    nl_name_1 = models.CharField(max_length=250, null=True, blank=True, default=None)
    
    gid_2 = models.ForeignKey(
        Admin_Level_2, on_delete=models.SET_DEFAULT, null=True, blank=True, default=None
    )
    gid_2_string = models.CharField(max_length=250, null=True, blank=True, default=None,
                                     help_text="Temp field for parallel loading")
    
    name_2 = models.CharField(max_length=250, null=True, blank=True, default=None)
    nl_name_2 = models.CharField(max_length=250, null=True, blank=True, default=None)
    gid_3 = models.CharField(max_length=250, null=True, blank=True, default=None)
    name_3 = models.CharField(max_length=250, null=True, blank=True, default=None)
    varname_3 = models.CharField(max_length=250, null=True, blank=True, default=None)
    nl_name_3 = models.CharField(max_length=250, null=True, blank=True, default=None)
    type_3 = models.CharField(max_length=250, null=True, blank=True, default=None)
    engtype_3 = models.CharField(max_length=250, null=True, blank=True, default=None)
    cc_3 = models.CharField(max_length=250, null=True, blank=True, default=None)
    hasc_3 = models.CharField(max_length=250, null=True, blank=True, default=None)

    # GeoDjango geometry Field

    geom = models.MultiPolygonField(srid=4326)

    def __str__(self):
        representative_string = (
            f"GID:{self.gid_3}, Name 3: {self.name_3} Country:{self.country}"
        )
        return representative_string

    class Meta:
        ordering = ["gid_3"]


# Auto-generated `LayerMapping` dictionary for Admin_Level_3 model
admin_level_3_mapping = {
    "gid_0": {"gid_0": "GID_0"},
    "country": "COUNTRY",
    "gid_1": {"gid_1": "GID_1"},
    "name_1": "NAME_1",
    "nl_name_1": "NL_NAME_1",
    "gid_2": {"gid_2": "GID_2"},
    "name_2": "NAME_2",
    "nl_name_2": "NL_NAME_2",
    "gid_3": "GID_3",
    "name_3": "NAME_3",
    "varname_3": "VARNAME_3",
    "nl_name_3": "NL_NAME_3",
    "type_3": "TYPE_3",
    "engtype_3": "ENGTYPE_3",
    "cc_3": "CC_3",
    "hasc_3": "HASC_3",
    "geom": "MULTIPOLYGON",
}


class Admin_Level_4(models.Model):
    # Foreign keys (populated after parallel load)
    gid_0 = models.ForeignKey(
        Admin_Level_0, on_delete=models.SET_DEFAULT, null=True, blank=True, default=None
    )
    gid_0_string = models.CharField(max_length=250, null=True, blank=True, default=None,
                                     help_text="Temp field for parallel loading")
    
    country = models.CharField(max_length=250, null=True, blank=True, default=None)
    
    gid_1 = models.ForeignKey(
        Admin_Level_1, on_delete=models.SET_DEFAULT, null=True, blank=True, default=None
    )
    gid_1_string = models.CharField(max_length=250, null=True, blank=True, default=None,
                                     help_text="Temp field for parallel loading")
    
    name_1 = models.CharField(max_length=250, null=True, blank=True, default=None)
    
    gid_2 = models.ForeignKey(
        Admin_Level_2, on_delete=models.SET_DEFAULT, null=True, blank=True, default=None
    )
    gid_2_string = models.CharField(max_length=250, null=True, blank=True, default=None,
                                     help_text="Temp field for parallel loading")
    
    name_2 = models.CharField(max_length=250, null=True, blank=True, default=None)
    
    gid_3 = models.ForeignKey(
        Admin_Level_3, on_delete=models.SET_DEFAULT, null=True, blank=True, default=None
    )
    gid_3_string = models.CharField(max_length=250, null=True, blank=True, default=None,
                                     help_text="Temp field for parallel loading")
    
    name_3 = models.CharField(max_length=250, null=True, blank=True, default=None)
    gid_4 = models.CharField(max_length=250, null=True, blank=True, default=None)
    name_4 = models.CharField(max_length=250, null=True, blank=True, default=None)
    varname_4 = models.CharField(max_length=250, null=True, blank=True, default=None)
    type_4 = models.CharField(max_length=250, null=True, blank=True, default=None)
    engtype_4 = models.CharField(max_length=250, null=True, blank=True, default=None)
    cc_4 = models.CharField(max_length=250, null=True, blank=True, default=None)

    # GeoDjango geometry field

    geom = models.MultiPolygonField(srid=4326)

    def __str__(self):
        representative_string = (
            f"GID:{self.gid_4}, Name 4: {self.name_4} Country:{self.country}"
        )
        return representative_string

    class Meta:
        ordering = ["gid_4"]


# Auto-generated `LayerMapping` dictionary for Admin_Level_4 model
admin_level_4_mapping = {
    "gid_4": "GID_4",
    "gid_0": {"gid_0": "GID_0"},
    "country": "COUNTRY",
    "gid_1": {"gid_1": "GID_1"},
    "name_1": "NAME_1",
    "gid_2": {"gid_2": "GID_2"},
    "name_2": "NAME_2",
    "gid_3": {"gid_3": "GID_3"},
    "name_3": "NAME_3",
    "name_4": "NAME_4",
    "varname_4": "VARNAME_4",
    "type_4": "TYPE_4",
    "engtype_4": "ENGTYPE_4",
    "cc_4": "CC_4",
    "geom": "MULTIPOLYGON",
}


class Admin_Level_5(models.Model):
    # Foreign keys (populated after parallel load)
    gid_0 = models.ForeignKey(
        Admin_Level_0, on_delete=models.SET_DEFAULT, null=True, blank=True, default=None
    )
    gid_0_string = models.CharField(max_length=250, null=True, blank=True, default=None,
                                     help_text="Temp field for parallel loading")
    
    country = models.CharField(max_length=250, null=True, blank=True, default=None)
    
    gid_1 = models.ForeignKey(
        Admin_Level_1, on_delete=models.SET_DEFAULT, null=True, blank=True, default=None
    )
    gid_1_string = models.CharField(max_length=250, null=True, blank=True, default=None,
                                     help_text="Temp field for parallel loading")
    
    name_1 = models.CharField(max_length=250, null=True, blank=True, default=None)
    
    gid_2 = models.ForeignKey(
        Admin_Level_2, on_delete=models.SET_DEFAULT, null=True, blank=True, default=None
    )
    gid_2_string = models.CharField(max_length=250, null=True, blank=True, default=None,
                                     help_text="Temp field for parallel loading")
    
    name_2 = models.CharField(max_length=250, null=True, blank=True, default=None)
    
    gid_3 = models.ForeignKey(
        Admin_Level_3, on_delete=models.SET_DEFAULT, null=True, blank=True, default=None
    )
    gid_3_string = models.CharField(max_length=250, null=True, blank=True, default=None,
                                     help_text="Temp field for parallel loading")
    
    name_3 = models.CharField(max_length=250, null=True, blank=True, default=None)
    
    gid_4 = models.ForeignKey(
        Admin_Level_4, on_delete=models.SET_DEFAULT, null=True, blank=True, default=None
    )
    gid_4_string = models.CharField(max_length=250, null=True, blank=True, default=None,
                                     help_text="Temp field for parallel loading")
    
    name_4 = models.CharField(max_length=250, null=True, blank=True, default=None)
    gid_5 = models.CharField(max_length=250, null=True, blank=True, default=None)
    name_5 = models.CharField(max_length=250, null=True, blank=True, default=None)
    type_5 = models.CharField(max_length=250, null=True, blank=True, default=None)
    engtype_5 = models.CharField(max_length=250, null=True, blank=True, default=None)
    cc_5 = models.CharField(max_length=250, null=True, blank=True, default=None)

    # GeoDjango Geometry Field
    geom = models.MultiPolygonField(srid=4326)

    def __str__(self):
        representative_string = (
            f"GID:{self.gid_5}, Name 5: {self.name_3} Country:{self.country}"
        )
        return representative_string

    class Meta:
        ordering = ["gid_5"]


# Auto-generated `LayerMapping` dictionary for Admin_Level_5 model
admin_level_5_mapping = {
    "gid_0": {"gid_0": "GID_0"},
    "country": "COUNTRY",
    "gid_1": {"gid_1": "GID_1"},
    "name_1": "NAME_1",
    "gid_2": {"gid_2": "GID_2"},
    "name_2": "NAME_2",
    "gid_3": {"gid_3": "GID_3"},
    "name_3": "NAME_3",
    "gid_4": {"gid_4": "GID_4"},
    "name_4": "NAME_4",
    "gid_5": "GID_5",
    "name_5": "NAME_5",
    "type_5": "TYPE_5",
    "engtype_5": "ENGTYPE_5",
    "cc_5": "CC_5",
    "geom": "MULTIPOLYGON",
}
