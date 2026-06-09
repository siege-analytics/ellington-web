"""
ZIP Code Tabulation Area (ZCTA) Model

ZCTAs are generalized areal representations of USPS ZIP Code service areas.
NOT exact ZIP codes (which are delivery routes), but approximations for statistical use.

Key uses:
- Donation analysis by ZIP code
- Cross-reference with VTDs, CDs, Counties
- Urban/suburban/rural classification

Sources:
- Census TIGER: https://www2.census.gov/geo/tiger/TIGER{year}/ZCTA520/
"""

from django.contrib.gis.db import models


class United_States_Census_ZCTA(models.Model):
    """
    ZIP Code Tabulation Area - statistical approximation of ZIP codes
    
    Year-aware: ZCTA boundaries updated every 10 years (2010, 2020, 2030)
    Annual vintages may have minor adjustments
    
    NOTE: ZCTAs cross state/county boundaries - no hierarchical relationships!
    """
    
    # Standard Census TIGER fields
    zcta5ce = models.CharField(max_length=5, help_text="5-digit ZCTA code")
    geoid = models.CharField(max_length=5, help_text="ZCTA GEOID (same as zcta5ce)")
    geoidfq = models.CharField(max_length=14, help_text="Fully qualified GEOID")
    classfp = models.CharField(max_length=2, help_text="FIPS class code (always B5 for ZCTA)")
    mtfcc = models.CharField(max_length=5, help_text="MAF/TIGER Feature Class Code")
    funcstat = models.CharField(max_length=1, help_text="Functional status")
    
    # Area measurements
    aland = models.BigIntegerField(help_text="Land area (sq meters)")
    awater = models.BigIntegerField(help_text="Water area (sq meters)")
    
    # Internal point
    intptlat = models.CharField(max_length=11, help_text="Latitude of internal point")
    intptlon = models.CharField(max_length=12, help_text="Longitude of internal point")
    
    # Geometry
    geom = models.MultiPolygonField(srid=4269, help_text="Boundary geometry (NAD83)")
    
    # Year
    year = models.IntegerField(help_text="Census year (typically 2010, 2020, etc.)")
    
    # NO HIERARCHICAL FKs - ZCTAs cross state/county boundaries!
    # Use intersection models instead (ZCTA-CD, ZCTA-County, etc.)
    
    class Meta:
        db_table = 'census_zcta'
        verbose_name = 'ZIP Code Tabulation Area'
        verbose_name_plural = 'ZIP Code Tabulation Areas'
        unique_together = [['geoid', 'year']]
        indexes = [
            models.Index(fields=['year']),
            models.Index(fields=['geoid', 'year']),
            models.Index(fields=['zcta5ce', 'year']),
        ]
        ordering = ['zcta5ce']
    
    def __str__(self):
        return f"ZCTA {self.zcta5ce} ({self.year})"


# LayerMapping dictionary for Census TIGER ZCTA files
# Note: Field names vary by year and vintage
# This is for ZCTA520 (2020-based, released in 2020+)
united_states_census_zcta_mapping_2020 = {
    'zcta5ce': 'ZCTA5CE20',
    'geoid': 'GEOID20',
    'geoidfq': 'GEOIDFQ20',
    'classfp': 'CLASSFP20',
    'mtfcc': 'MTFCC20',
    'funcstat': 'FUNCSTAT20',
    'aland': 'ALAND20',
    'awater': 'AWATER20',
    'intptlat': 'INTPTLAT20',
    'intptlon': 'INTPTLON20',
    'geom': 'MULTIPOLYGON',
}

# For 2010 ZCTAs (field names different)
united_states_census_zcta_mapping_2010 = {
    'zcta5ce': 'ZCTA5CE10',
    'geoid': 'GEOID10',
    'geoidfq': 'GEOIDFQ10',
    'classfp': 'CLASSFP10',
    'mtfcc': 'MTFCC10',
    'funcstat': 'FUNCSTAT10',
    'aland': 'ALAND10',
    'awater': 'AWATER10',
    'intptlat': 'INTPTLAT10',
    'intptlon': 'INTPTLON10',
    'geom': 'MULTIPOLYGON',
}

# For recent years (2021-2025), fields may not have year suffix
united_states_census_zcta_mapping_current = {
    'zcta5ce': 'ZCTA5CE',
    'geoid': 'GEOID',
    'geoidfq': 'GEOIDFQ',
    'classfp': 'CLASSFP',
    'mtfcc': 'MTFCC',
    'funcstat': 'FUNCSTAT',
    'aland': 'ALAND',
    'awater': 'AWATER',
    'intptlat': 'INTPTLAT',
    'intptlon': 'INTPTLON',
    'geom': 'MULTIPOLYGON',
}

