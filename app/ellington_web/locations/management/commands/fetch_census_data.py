"""
Universal Census TIGER data fetcher - supports all unit types and years

Replaces multiple specific commands with one unified interface.

Usage:
    # Fetch 2024 Congressional Districts
    python manage.py fetch_census_data --unit cd --year 2024 --async
    
    # Fetch 2020 Counties for all states
    python manage.py fetch_census_data --unit county --year 2020 --all-states --async
    
    # Fetch 2023 Places for California
    python manage.py fetch_census_data --unit place --year 2023 --state CA --async
    
    # Load all years 2020-2024 for Congressional Districts
    python manage.py fetch_census_data --unit cd --start-year 2020 --end-year 2024 --async

Supported units:
- state: States
- county: Counties
- cd: Congressional Districts
- sldu: State Legislative Districts (Upper Chamber)
- sldl: State Legislative Districts (Lower Chamber)
- tract: Census Tracts
- blockgroup: Block Groups
- tabblock: Tabulation Blocks (2010, 2020 only - very large!)
- vtd: Voter Tabulation Districts
- place: Places (cities/towns)
- zcta: ZIP Code Tabulation Areas
"""

from django.core.management.base import BaseCommand, CommandError
from django.contrib.gis.utils import LayerMapping
from pathlib import Path
import requests
import zipfile
import tempfile
import logging

logger = logging.getLogger(__name__)

# State FIPS codes
STATE_FIPS = {
    'AL': '01', 'AK': '02', 'AZ': '04', 'AR': '05', 'CA': '06', 'CO': '08',
    'CT': '09', 'DE': '10', 'FL': '12', 'GA': '13', 'HI': '15', 'ID': '16',
    'IL': '17', 'IN': '18', 'IA': '19', 'KS': '20', 'KY': '21', 'LA': '22',
    'ME': '23', 'MD': '24', 'MA': '25', 'MI': '26', 'MN': '27', 'MS': '28',
    'MO': '29', 'MT': '30', 'NE': '31', 'NV': '32', 'NH': '33', 'NJ': '34',
    'NM': '35', 'NY': '36', 'NC': '37', 'ND': '38', 'OH': '39', 'OK': '40',
    'OR': '41', 'PA': '42', 'RI': '44', 'SC': '45', 'SD': '46', 'TN': '47',
    'TX': '48', 'UT': '49', 'VT': '50', 'VA': '51', 'WA': '53', 'WV': '54',
    'WI': '55', 'WY': '56', 'DC': '11', 'PR': '72'
}

# Unit type configuration
UNIT_CONFIG = {
    'state': {
        'model': 'United_States_Census_State',
        'mapping': 'united_states_census_state_mapping',
        'url_pattern': 'https://www2.census.gov/geo/tiger/TIGER{year}/STATE/tl_{year}_us_state.zip',
        'needs_state_fips': False,
        'shapefile_pattern': 'tl_{year}_us_state.shp',
    },
    'county': {
        'model': 'United_States_Census_County',
        'mapping': 'united_states_census_county_mapping',
        'url_pattern': 'https://www2.census.gov/geo/tiger/TIGER{year}/COUNTY/tl_{year}_us_county.zip',
        'needs_state_fips': False,
        'shapefile_pattern': 'tl_{year}_us_county.shp',
    },
    'cd': {
        'model': 'United_States_Census_Congressional_District',
        'mapping': 'united_states_census_congressional_district_mapping',
        'url_pattern': 'https://www2.census.gov/geo/tiger/TIGER{year}/CD/tl_{year}_us_cd{congress}.zip',
        'needs_state_fips': False,
        'shapefile_pattern': 'tl_{year}_us_cd{congress}.shp',
        'needs_congress_number': True,
    },
    'sldu': {
        'model': 'United_States_Census_State_Legislative_District_Upper',
        'mapping': 'united_states_census_state_legislative_district_upper_mapping',
        'url_pattern': 'https://www2.census.gov/geo/tiger/TIGER{year}/SLDU/tl_{year}_{state_fips}_sldu.zip',
        'needs_state_fips': True,
        'shapefile_pattern': 'tl_{year}_{state_fips}_sldu.shp',
    },
    'sldl': {
        'model': 'United_States_Census_State_Legislative_District_Lower',
        'mapping': 'united_states_census_state_legislative_district_lower_mapping',
        'url_pattern': 'https://www2.census.gov/geo/tiger/TIGER{year}/SLDL/tl_{year}_{state_fips}_sldl.zip',
        'needs_state_fips': True,
        'shapefile_pattern': 'tl_{year}_{state_fips}_sldl.shp',
    },
    'tract': {
        'model': 'United_States_Census_Tract',
        'mapping': 'united_states_census_tract_mapping',
        'url_pattern': 'https://www2.census.gov/geo/tiger/TIGER{year}/TRACT/tl_{year}_{state_fips}_tract.zip',
        'needs_state_fips': True,
        'shapefile_pattern': 'tl_{year}_{state_fips}_tract.shp',
    },
    'blockgroup': {
        'model': 'United_States_Census_Block_Group',
        'mapping': 'united_states_census_block_group_mapping',
        'url_pattern': 'https://www2.census.gov/geo/tiger/TIGER{year}/BG/tl_{year}_{state_fips}_bg.zip',
        'needs_state_fips': True,
        'shapefile_pattern': 'tl_{year}_{state_fips}_bg.shp',
    },
    'tabblock': {
        'model': 'United_States_Census_Tabulation_Block',
        'mapping': 'united_states_census_tabulation_block_mapping',
        'url_pattern': 'https://www2.census.gov/geo/tiger/TIGER{year}/TABBLOCK{decade}/tl_{year}_{state_fips}_tabblock{decade}.zip',
        'needs_state_fips': True,
        'shapefile_pattern': 'tl_{year}_{state_fips}_tabblock{decade}.shp',
        'needs_decade': True,  # Only 2010, 2020
    },
    'vtd': {
        'model': 'United_States_Census_Voter_Tabulation_District',
        'mapping': 'united_states_census_voter_tabulation_district_mapping',
        'url_pattern': 'https://www2.census.gov/geo/tiger/TIGER{year}/VTD/tl_{year}_{state_fips}_vtd{decade}.zip',
        'needs_state_fips': True,
        'shapefile_pattern': 'tl_{year}_{state_fips}_vtd{decade}.shp',
        'needs_decade': True,  # Different files for 2010 vs 2020
    },
    'place': {
        'model': 'United_States_Census_Place',
        'mapping': 'united_states_census_place_mapping',
        'url_pattern': 'https://www2.census.gov/geo/tiger/TIGER{year}/PLACE/tl_{year}_{state_fips}_place.zip',
        'needs_state_fips': True,
        'shapefile_pattern': 'tl_{year}_{state_fips}_place.shp',
    },
    'zcta': {
        'model': 'United_States_Census_ZCTA',
        'mapping': 'united_states_census_zcta_mapping',
        'url_pattern': 'https://www2.census.gov/geo/tiger/TIGER{year}/ZCTA520/tl_{year}_us_zcta520.zip',
        'needs_state_fips': False,
        'shapefile_pattern': 'tl_{year}_us_zcta520.shp',
    },
}


def get_congress_number(year):
    """
    Get Congress number from year
    118th Congress: 2023-2024
    119th Congress: 2025-2026
    etc.
    """
    # 118th Congress started Jan 2023
    return 118 + ((year - 2023) // 2)


def get_decade(year):
    """Get decade marker for files (10, 20, 30)"""
    if year < 2015:
        return 10
    elif year < 2025:
        return 20
    else:
        return 30


class Command(BaseCommand):
    help = 'Fetch and load Census TIGER data for any unit type and year'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--unit',
            type=str,
            required=True,
            choices=list(UNIT_CONFIG.keys()),
            help='Census unit type to fetch'
        )
        
        parser.add_argument(
            '--year',
            type=int,
            help='Single year to fetch (e.g., 2024)'
        )
        
        parser.add_argument(
            '--start-year',
            type=int,
            help='Start year for range (use with --end-year)'
        )
        
        parser.add_argument(
            '--end-year',
            type=int,
            help='End year for range (use with --start-year)'
        )
        
        parser.add_argument(
            '--state',
            type=str,
            help='State FIPS code (e.g., 06 for CA) or abbreviation (e.g., CA)'
        )
        
        parser.add_argument(
            '--all-states',
            action='store_true',
            help='Fetch for all 50 states + DC + PR'
        )
        
        parser.add_argument(
            '--async',
            action='store_true',
            dest='use_async',
            help='Run via Celery (recommended for large datasets)'
        )
        
        parser.add_argument(
            '--skip-download',
            action='store_true',
            help='Skip download if file already exists'
        )
    
    def handle(self, *args, **options):
        unit_type = options['unit']
        year = options.get('year')
        start_year = options.get('start_year')
        end_year = options.get('end_year')
        state = options.get('state')
        all_states = options.get('all_states')
        use_async = options.get('use_async')
        skip_download = options.get('skip_download')
        
        # Determine years to process
        if year:
            years_to_process = [year]
        elif start_year and end_year:
            years_to_process = list(range(start_year, end_year + 1))
        else:
            raise CommandError("Must specify --year or both --start-year and --end-year")
        
        # Determine states to process
        config = UNIT_CONFIG[unit_type]
        if config['needs_state_fips']:
            if all_states:
                states_to_process = list(STATE_FIPS.values())
            elif state:
                state_fips = STATE_FIPS.get(state.upper(), state)
                states_to_process = [state_fips]
            else:
                raise CommandError(f"{unit_type} requires --state or --all-states")
        else:
            states_to_process = [None]  # National files
        
        # If async, dispatch to Celery
        if use_async:
            from locations.tasks import fetch_census_unit_task
            for year in years_to_process:
                for state_fips in states_to_process:
                    task_args = {
                        'unit_type': unit_type,
                        'year': year,
                        'state_fips': state_fips,
                        'skip_download': skip_download
                    }
                    fetch_census_unit_task.delay(**task_args)
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'✓ Queued: {unit_type} {year} {state_fips or "national"}'
                        )
                    )
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'\n{len(years_to_process) * len(states_to_process)} tasks queued!'
                )
            )
            return
        
        # Synchronous processing
        for year in years_to_process:
            for state_fips in states_to_process:
                try:
                    self._fetch_and_load(
                        unit_type=unit_type,
                        year=year,
                        state_fips=state_fips,
                        skip_download=skip_download
                    )
                except Exception as e:
                    logger.error(f"Error processing {unit_type} {year} {state_fips}: {e}")
                    self.stdout.write(
                        self.style.ERROR(f'✗ Failed: {unit_type} {year} {state_fips or "national"}')
                    )
    
    def _fetch_and_load(self, unit_type, year, state_fips=None, skip_download=False):
        """Fetch and load data for one unit/year/state combination"""
        config = UNIT_CONFIG[unit_type]
        
        # Build URL
        url = config['url_pattern'].format(
            year=year,
            state_fips=state_fips,
            congress=get_congress_number(year) if config.get('needs_congress_number') else None,
            decade=get_decade(year) if config.get('needs_decade') else None
        )
        
        shapefile_name = config['shapefile_pattern'].format(
            year=year,
            state_fips=state_fips,
            congress=get_congress_number(year) if config.get('needs_congress_number') else None,
            decade=get_decade(year) if config.get('needs_decade') else None
        )
        
        self.stdout.write(f"Fetching {unit_type} {year} {state_fips or 'national'}...")
        self.stdout.write(f"URL: {url}")
        
        # Download and extract
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            zip_path = tmpdir_path / f"{unit_type}_{year}_{state_fips or 'national'}.zip"
            
            # Download
            if not skip_download or not zip_path.exists():
                response = requests.get(url, stream=True, timeout=300)
                response.raise_for_status()
                
                with open(zip_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
            
            # Extract
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(tmpdir_path)
            
            # Find shapefile
            shapefile_path = tmpdir_path / shapefile_name
            if not shapefile_path.exists():
                raise FileNotFoundError(f"Shapefile not found: {shapefile_name}")
            
            # Load into database
            from locations.models.census.tiger import *
            
            model = globals()[config['model']]
            mapping_dict = globals()[config['mapping']]
            
            lm = LayerMapping(
                model,
                str(shapefile_path),
                mapping_dict,
                transform=False,
                encoding='utf-8'
            )
            
            # Save with year
            lm.save(strict=True, verbose=True)
            
            # Set year on all records (LayerMapping doesn't handle computed fields)
            model.objects.filter(year__isnull=True).update(year=year)
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'✓ Loaded: {unit_type} {year} {state_fips or "national"}'
                )
            )

