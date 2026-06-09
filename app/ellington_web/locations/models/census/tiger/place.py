"""
Census Place (Incorporated Place and Census Designated Place)

Places are cities, towns, villages, boroughs, and Census Designated Places (CDPs).
Critical for understanding urban vs rural donation patterns.

Sources:
- Census TIGER: https://www2.census.gov/geo/tiger/TIGER{year}/PLACE/
"""

from django.contrib.gis.db import models


class United_States_Census_Place(models.Model):
    """
    Census Place - cities, towns, and Census Designated Places
    
    Year-aware: Place boundaries change annually (annexations, incorporations)
    """
    
    # Standard Census TIGER fields
    statefp = models.CharField(max_length=2, help_text="State FIPS code")
    placefp = models.CharField(max_length=5, help_text="Place FIPS code")
    placens = models.CharField(max_length=8, help_text="GNIS feature ID")
    geoid = models.CharField(max_length=7, help_text="State+Place FIPS")
    geoidfq = models.CharField(max_length=16, help_text="Fully qualified GEOID")
    name = models.CharField(max_length=100, help_text="Place name")
    namelsad = models.CharField(max_length=100, help_text="Legal/Statistical Area Description")
    lsad = models.CharField(max_length=2, help_text="Legal/Statistical Area Description code")
    classfp = models.CharField(max_length=2, help_text="FIPS class code")
    cpi = models.CharField(max_length=1, null=True, blank=True, help_text="Current place indicator")
    pcicbsa = models.CharField(max_length=1, null=True, blank=True, help_text="Principal city indicator")
    pcinecta = models.CharField(max_length=1, null=True, blank=True, help_text="NECTA principal city indicator")
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
    year = models.IntegerField(help_text="Census year")
    
    # ==== INTER-RELATIONS: Hierarchical ForeignKey ====
    # Optional FK for rich queries (keep GEOIDs as primary)
    state = models.ForeignKey(
        'United_States_Census_State',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='places',
        db_constraint=False,  # No DB-level constraint (year flexibility)
        help_text="Parent state (populated from statefp + year)"
    )
    
    class Meta:
        db_table = 'census_place'
        verbose_name = 'Census Place'
        verbose_name_plural = 'Census Places'
        unique_together = [['geoid', 'year']]
        indexes = [
            models.Index(fields=['year', 'statefp']),
            models.Index(fields=['geoid', 'year']),
            models.Index(fields=['name', 'year']),
            models.Index(fields=['classfp']),  # Filter incorporated vs CDP
        ]
        ordering = ['statefp', 'name']
    
    def __str__(self):
        return f"{self.namelsad} ({self.year})"
    
    def populate_parent_relationships(self):
        """
        Populate state ForeignKey from FIPS code
        Called after Place is loaded to establish hierarchical relationships
        """
        from .state import United_States_Census_State
        self.state = United_States_Census_State.objects.filter(
            statefp=self.statefp,
            year=self.year
        ).first()
        
        if self.state:
            self.save()
            return True
        
        return False


# LayerMapping dictionary for Census TIGER Place files
united_states_census_place_mapping = {
    'statefp': 'STATEFP',
    'placefp': 'PLACEFP',
    'placens': 'PLACENS',
    'geoid': 'GEOID',
    'geoidfq': 'GEOIDFQ',
    'name': 'NAME',
    'namelsad': 'NAMELSAD',
    'lsad': 'LSAD',
    'classfp': 'CLASSFP',
    'cpi': 'CPI',
    'pcicbsa': 'PCICBSA',
    'pcinecta': 'PCINECTA',
    'mtfcc': 'MTFCC',
    'funcstat': 'FUNCSTAT',
    'aland': 'ALAND',
    'awater': 'AWATER',
    'intptlat': 'INTPTLAT',
    'intptlon': 'INTPTLON',
    'geom': 'MULTIPOLYGON',
}

