"""
Fetch and load Census Voter Tabulation Districts (VTDs)

VTDs are the smallest geographic units for which election results are tabulated.
Essential for precinct-level analysis and voter geography.

Sources:
- Census TIGER: https://www2.census.gov/geo/tiger/TIGER{year}/VTD/
- Redistricting Data Hub: https://redistrictingdatahub.org/

Usage:
    # Fetch 2020 VTDs for California
    python manage.py fetch_census_vtds --year 2020 --state 06
    
    # Fetch for all states (via Celery)
    python manage.py fetch_census_vtds --year 2020 --all-states --async
    
    # Fetch both 2010 and 2020
    python manage.py fetch_census_vtds --year 2010 --state 06
    python manage.py fetch_census_vtds --year 2020 --state 06
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


class Command(BaseCommand):
    help = 'Fetch and load Census Voter Tabulation Districts (VTDs)'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--year',
            type=int,
            required=True,
            choices=[2010, 2020],
            help='Census year (2010 or 2020)'
        )
        
        parser.add_argument(
            '--state',
            type=str,
            help='State FIPS code (e.g., 06 for CA) or abbreviation (e.g., CA)'
        )
        
        parser.add_argument(
            '--all-states',
            action='store_true',
            help='Fetch VTDs for all 50 states + DC'
        )
        
        parser.add_argument(
            '--async',
            action='store_true',
            dest='use_async',
            help='Run via Celery (recommended for all-states)'
        )
        
        parser.add_argument(
            '--skip-download',
            action='store_true',
            help='Skip download if file already exists'
        )
    
    def handle(self, *args, **options):
        year = options['year']
        state = options.get('state')
        all_states = options.get('all_states')
        use_async = options.get('use_async')
        skip_download = options.get('skip_download')
        
        # Determine which states to process
        if all_states:
            states_to_process = list(STATE_FIPS.values())
        elif state:
            # Convert abbreviation to FIPS if needed
            state_fips = STATE_FIPS.get(state.upper(), state)
            states_to_process = [state_fips]
        else:
            raise CommandError("Must specify --state or --all-states")
        
        self.stdout.write(f"Processing {len(states_to_process)} state(s) for year {year}")
        
        if use_async:
            # Queue Celery tasks
            from locations.tasks import fetch_and_load_vtd_state
            
            for state_fips in states_to_process:
                result = fetch_and_load_vtd_state.delay(year, state_fips)
                self.stdout.write(f"  Queued {state_fips}: task {result.id}")
            
            self.stdout.write(self.style.SUCCESS(f"✅ Queued {len(states_to_process)} tasks"))
            self.stdout.write("Monitor progress in Flower: http://localhost:5555")
        
        else:
            # Process synchronously
            for state_fips in states_to_process:
                try:
                    self._fetch_and_load_state(year, state_fips, skip_download)
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"  ❌ Failed {state_fips}: {e}"))
    
    def _fetch_and_load_state(self, year, state_fips, skip_download=False):
        """Fetch and load VTDs for a single state"""
        from locations.models.census.tiger.vtd import (
            United_States_Census_Voter_Tabulation_District,
            united_states_census_voter_tabulation_district_mapping,
            united_states_census_voter_tabulation_district_mapping_2010
        )
        
        self.stdout.write(f"\n{'='*70}")
        self.stdout.write(f"Processing State {state_fips} - Year {year}")
        self.stdout.write(f"{'='*70}")
        
        # Construct download URL
        if year == 2020:
            url = f"https://www2.census.gov/geo/tiger/TIGER2020/VTD/tl_2020_{state_fips}_vtd20.zip"
            mapping = united_states_census_voter_tabulation_district_mapping
        elif year == 2010:
            url = f"https://www2.census.gov/geo/tiger/TIGER2010/VTD/2010/tl_2010_{state_fips}_vtd10.zip"
            mapping = united_states_census_voter_tabulation_district_mapping_2010
        else:
            raise CommandError(f"Unsupported year: {year}")
        
        # Download directory
        from django.conf import settings
        download_dir = settings.VECTOR_SPATIAL_DATA_SUBDIRECTORY / "census_vtd" / f"{year}"
        download_dir.mkdir(parents=True, exist_ok=True)
        
        zip_path = download_dir / f"tl_{year}_{state_fips}_vtd{year%100}.zip"
        extract_dir = download_dir / f"tl_{year}_{state_fips}_vtd{year%100}"
        
        # Download if needed
        if not skip_download or not zip_path.exists():
            self.stdout.write(f"Downloading from {url}...")
            
            response = requests.get(url, stream=True)
            response.raise_for_status()
            
            with open(zip_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            self.stdout.write(f"  ✅ Downloaded {zip_path.name}")
        else:
            self.stdout.write(f"  ✅ Using existing {zip_path.name}")
        
        # Extract
        if not extract_dir.exists() or not skip_download:
            self.stdout.write(f"Extracting...")
            
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
            
            self.stdout.write(f"  ✅ Extracted to {extract_dir}")
        
        # Find shapefile
        shp_file = list(extract_dir.glob("*.shp"))[0]
        
        self.stdout.write(f"Loading from {shp_file.name}...")
        
        # Load using LayerMapping
        lm = LayerMapping(
            United_States_Census_Voter_Tabulation_District,
            str(shp_file),
            mapping,
            transform=False,
            encoding='utf-8'
        )
        
        # Count before
        before_count = United_States_Census_Voter_Tabulation_District.objects.filter(
            statefp=state_fips,
            year=year
        ).count()
        
        # Load (save to database)
        lm.save(strict=True, verbose=False, progress=True)
        
        # Set year on newly loaded records (LayerMapping doesn't handle this automatically)
        United_States_Census_Voter_Tabulation_District.objects.filter(
            statefp=state_fips,
            year__isnull=True
        ).update(year=year)
        
        # Count after
        after_count = United_States_Census_Voter_Tabulation_District.objects.filter(
            statefp=state_fips,
            year=year
        ).count()
        
        loaded = after_count - before_count
        
        self.stdout.write(self.style.SUCCESS(f"  ✅ Loaded {loaded} VTDs for state {state_fips} ({year})"))
        self.stdout.write(f"  Total in DB: {after_count}")

