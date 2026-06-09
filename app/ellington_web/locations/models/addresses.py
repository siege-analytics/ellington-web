from __future__ import unicode_literals
from django.contrib.gis.db import models
from django.utils import timezone

# This address definition is based on the Smarty Streets definition for now


class United_States_Address(models.Model):

    # This is an address in the US

    primary_number = models.CharField(
        max_length=250, null=True, blank=True, default=None
    )
    street_name = models.CharField(max_length=250, null=True, blank=True, default=None)
    street_suffix = models.CharField(
        max_length=250, null=True, blank=True, default=None
    )
    city_name = models.CharField(max_length=250, null=True, blank=True, default=None)
    default_city_name = models.CharField(
        max_length=250, null=True, blank=True, default=None
    )
    state_abbreviation = models.CharField(
        max_length=2, null=True, blank=True, default=None
    )
    zip5 = models.CharField(max_length=5, null=True, blank=True, default=None)
    plus4_code = models.CharField(max_length=4, null=True, blank=True, default=None)
    delivery_point = models.CharField(
        max_length=99, null=True, blank=True, default=None
    )
    delivery_point_check_digit = models.CharField(
        max_length=99, null=True, blank=True, default=None
    )
    record_type = models.CharField(max_length=250, null=True, blank=True, default=None)
    zip_type = models.CharField(max_length=250, null=True, blank=True, default=None)
    county_fips = models.CharField(max_length=250, null=True, blank=True, default=None)
    county_name = models.CharField(max_length=250, null=True, blank=True, default=None)
    carrier_route = models.CharField(
        max_length=250, null=True, blank=True, default=None
    )
    congressional_district = models.CharField(
        max_length=250, null=True, blank=True, default=None
    )
    rdi = models.CharField(max_length=250, null=True, blank=True, default=None)
    elot_sequence = models.CharField(
        max_length=250, null=True, blank=True, default=None
    )
    elot_sort = models.CharField(max_length=250, null=True, blank=True, default=None)
    latitude = models.DecimalField(
        max_digits=22, decimal_places=16, null=True, blank=True, default=None
    )
    longitude = models.DecimalField(
        max_digits=22, decimal_places=16, null=True, blank=True, default=None
    )
    coordinate_license = models.CharField(
        max_length=250, null=True, blank=True, default=None
    )
    precision = models.CharField(max_length=250, null=True, blank=True, default=None)
    time_zone = models.CharField(max_length=250, null=True, blank=True, default=None)
    utc_offset = models.CharField(max_length=250, null=True, blank=True, default=None)

    # geodjango geometry field
    geom = models.PointField(srid=4326, null=True, blank=True, default=None)
    
    # Geocoding metadata
    geocoded = models.BooleanField(default=False, help_text="Whether address has been geocoded")
    geocode_quality = models.CharField(
        max_length=20, null=True, blank=True,
        help_text="Quality: Rooftop, Interpolated, Approximate, Zip"
    )
    geocode_source = models.CharField(
        max_length=50, null=True, blank=True,
        help_text="Source: Census, Google, Nominatim, SmartyStreets"
    )
    geocoded_at = models.DateTimeField(null=True, blank=True)
    
    # Year for census unit assignment (which boundaries to use)
    census_year = models.IntegerField(
        default=2020,
        help_text="Census year for boundary assignment (2010, 2020)"
    )
    
    # Census unit linkages (year-specific via census_year)
    # Stored as GEOIDs (strings) for flexibility across years
    state_geoid = models.CharField(max_length=2, null=True, blank=True)
    county_geoid = models.CharField(max_length=5, null=True, blank=True)
    tract_geoid = models.CharField(max_length=11, null=True, blank=True)
    block_group_geoid = models.CharField(max_length=12, null=True, blank=True)
    block_geoid = models.CharField(max_length=15, null=True, blank=True)
    vtd_geoid = models.CharField(max_length=11, null=True, blank=True)
    cd_geoid = models.CharField(max_length=4, null=True, blank=True)
    
    # Metadata
    census_units_assigned_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'locations_address'
        indexes = [
            models.Index(fields=['zip5', 'plus4_code']),
            models.Index(fields=['state_abbreviation', 'city_name']),
            models.Index(fields=['county_fips']),
            models.Index(fields=['congressional_district']),
            models.Index(fields=['census_year']),
            models.Index(fields=['geocoded']),
            models.Index(fields=['state_geoid', 'county_geoid']),
            models.Index(fields=['cd_geoid', 'census_year']),
            models.Index(fields=['vtd_geoid', 'census_year']),
        ]
    
    def __str__(self):
        representative_string = (
            f"{self.primary_number} {self.street_name} {self.street_suffix}"
        )
        return representative_string
    
    def assign_census_units(self, year=None):
        """
        Assign census geographic units via spatial join
        
        Args:
            year: Census year to use (2010 or 2020). If None, uses self.census_year
        
        Returns:
            bool: True if successful, False if no geometry or units not found
        """
        if not self.geom:
            return False
        
        year = year or self.census_year
        
        from django.contrib.gis.measure import D
        from .census.tiger import (
            United_States_Census_State,
            United_States_Census_County,
            United_States_Census_Tract,
            United_States_Census_Block_Group,
            United_States_Census_Tabulation_Block,
            United_States_Census_Congressional_District,
            United_States_Census_Voter_Tabulation_District
        )
        
        # State
        state = United_States_Census_State.objects.filter(
            geom__contains=self.geom,
            year=year
        ).first()
        
        if state:
            self.state_geoid = state.geoid
            
            # County (within state)
            county = United_States_Census_County.objects.filter(
                geom__contains=self.geom,
                statefp=state.statefp,
                year=year
            ).first()
            
            if county:
                self.county_geoid = county.geoid
                
                # Tract (within county)
                tract = United_States_Census_Tract.objects.filter(
                    geom__contains=self.geom,
                    statefp=state.statefp,
                    countyfp=county.countyfp,
                    year=year
                ).first()
                
                if tract:
                    self.tract_geoid = tract.geoid
                    
                    # Block group (within tract)
                    bg = United_States_Census_Block_Group.objects.filter(
                        geom__contains=self.geom,
                        statefp=state.statefp,
                        countyfp=county.countyfp,
                        tractce=tract.tractce,
                        year=year
                    ).first()
                    
                    if bg:
                        self.block_group_geoid = bg.geoid
                    
                    # Block (within tract - most specific)
                    block = United_States_Census_Tabulation_Block.objects.filter(
                        geom__contains=self.geom,
                        statefp20=state.statefp,
                        countyfp20=county.countyfp,
                        tractce20=tract.tractce,
                        year=year
                    ).first()
                    
                    if block:
                        self.block_geoid = block.geoid20
                
                # VTD (voting tabulation district)
                vtd = United_States_Census_Voter_Tabulation_District.objects.filter(
                    geom__contains=self.geom,
                    statefp=state.statefp,
                    countyfp=county.countyfp,
                    year=year
                ).first()
                
                if vtd:
                    self.vtd_geoid = vtd.geoid
            
            # Congressional district (may span counties)
            cd = United_States_Census_Congressional_District.objects.filter(
                geom__contains=self.geom,
                statefp=state.statefp,
                year=year
            ).first()
            
            if cd:
                self.cd_geoid = cd.geoid
        
        self.census_year = year
        self.census_units_assigned_at = timezone.now()
        self.save()
        
        return True
