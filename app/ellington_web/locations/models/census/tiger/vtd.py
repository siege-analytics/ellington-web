"""
Voter Tabulation District (VTD) Model

VTDs are the smallest geographic units for which election results are tabulated.
Often correspond to precincts, but not always.

Key for:
- Precinct-level election analysis
- Voter registration data
- Redistricting analysis

Sources:
- Census TIGER: Basic boundaries
- Redistricting Data Hub: Enhanced with election data
"""

from django.contrib.gis.db import models


class United_States_Census_Voter_Tabulation_District(models.Model):
    """
    Voter Tabulation District - smallest unit for election results
    
    Year-aware: VTDs are defined per redistricting cycle
    - 2010 VTDs: Used for 2012-2020 elections
    - 2020 VTDs: Used for 2022-2030 elections
    """
    
    # Standard Census TIGER fields
    statefp = models.CharField(max_length=2, help_text="State FIPS code")
    countyfp = models.CharField(max_length=3, help_text="County FIPS code")
    vtdst = models.CharField(max_length=6, help_text="VTD code")
    geoid = models.CharField(max_length=11, help_text="State+County+VTD")
    vtdi = models.CharField(max_length=1, null=True, blank=True, help_text="VTD indicator")
    name = models.CharField(max_length=100, help_text="VTD name")
    namelsad = models.CharField(max_length=100, help_text="Legal/Statistical Area Description")
    lsad = models.CharField(max_length=2, help_text="Legal/Statistical Area Description code")
    mtfcc = models.CharField(max_length=5, help_text="MAF/TIGER Feature Class Code")
    funcstat = models.CharField(max_length=1, help_text="Functional status")
    
    # Area measurements
    aland = models.BigIntegerField(help_text="Land area (sq meters)")
    awater = models.BigIntegerField(help_text="Water area (sq meters)")
    
    # Internal point (representative point within polygon)
    intptlat = models.CharField(max_length=11, help_text="Latitude of internal point")
    intptlon = models.CharField(max_length=12, help_text="Longitude of internal point")
    
    # Geometry
    geom = models.MultiPolygonField(srid=4269, help_text="Boundary geometry (NAD83)")
    
    # Year (redistricting cycle)
    year = models.IntegerField(
        help_text="Redistricting year (2010, 2020, 2030)"
    )
    
    # Enhanced fields (from Redistricting Data Hub or state sources)
    precinct_name = models.CharField(
        max_length=200, 
        null=True, 
        blank=True,
        help_text="Precinct name (if different from VTD name)"
    )
    precinct_code = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text="Local precinct code/ID"
    )
    
    # Electoral data (if available from enhanced sources)
    registered_voters = models.IntegerField(
        null=True,
        blank=True,
        help_text="Registered voters (if available)"
    )
    
    # Data source tracking
    source = models.CharField(
        max_length=50,
        default='CENSUS_TIGER',
        help_text="Data source (CENSUS_TIGER, RDH, STATE)"
    )
    
    class Meta:
        db_table = 'census_vtd'
        verbose_name = 'Voter Tabulation District'
        verbose_name_plural = 'Voter Tabulation Districts'
        unique_together = [['geoid', 'year']]
        indexes = [
            models.Index(fields=['year', 'statefp']),
            models.Index(fields=['year', 'statefp', 'countyfp']),
            models.Index(fields=['geoid', 'year']),
            models.Index(fields=['name']),
        ]
        ordering = ['statefp', 'countyfp', 'vtdst']
    
    def __str__(self):
        return f"{self.namelsad} ({self.geoid}, {self.year})"


# LayerMapping dictionary for Census TIGER VTD files
united_states_census_voter_tabulation_district_mapping = {
    'statefp': 'STATEFP20',
    'countyfp': 'COUNTYFP20',
    'vtdst': 'VTDST20',
    'geoid': 'GEOID20',
    'vtdi': 'VTDI20',
    'name': 'NAME20',
    'namelsad': 'NAMELSAD20',
    'lsad': 'LSAD20',
    'mtfcc': 'MTFCC20',
    'funcstat': 'FUNCSTAT20',
    'aland': 'ALAND20',
    'awater': 'AWATER20',
    'intptlat': 'INTPTLAT20',
    'intptlon': 'INTPTLON20',
    'geom': 'MULTIPOLYGON',
}

# For 2010 VTDs (field names different)
united_states_census_voter_tabulation_district_mapping_2010 = {
    'statefp': 'STATEFP10',
    'countyfp': 'COUNTYFP10',
    'vtdst': 'VTDST10',
    'geoid': 'GEOID10',
    'vtdi': 'VTDI10',
    'name': 'NAME10',
    'namelsad': 'NAMELSAD10',
    'lsad': 'LSAD10',
    'mtfcc': 'MTFCC10',
    'funcstat': 'FUNCSTAT10',
    'aland': 'ALAND10',
    'awater': 'AWATER10',
    'intptlat': 'INTPTLAT10',
    'intptlon': 'INTPTLON10',
    'geom': 'MULTIPOLYGON',
}

