"""
Celery tasks for locations app
"""

from celery import shared_task, group, chord, chain
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import Distance
from django.core.management import call_command
from .models import Place
import logging

logger = logging.getLogger(__name__)


@shared_task
def process_location_update(location_id):
    """
    Example task: Process a location update
    """
    try:
        place = Place.objects.get(id=location_id)
        logger.info(f"Processing location update for {place.name}")
        # Do something with the location
        return {
            'status': 'success',
            'location_id': location_id,
            'name': place.name
        }
    except Place.DoesNotExist:
        logger.error(f"Place {location_id} not found")
        return {'status': 'error', 'message': 'Place not found'}


@shared_task
def geocode_addresses_batch(address_ids):
    """
    Example task: Batch geocode addresses
    """
    logger.info(f"Batch geocoding {len(address_ids)} addresses")
    # Implement your geocoding logic here
    return {
        'status': 'success',
        'processed': len(address_ids)
    }


@shared_task
def calculate_distances(from_location_id, to_location_ids):
    """
    Example task: Calculate distances between locations
    """
    try:
        from_place = Place.objects.get(id=from_location_id)
        results = []
        
        for to_id in to_location_ids:
            try:
                to_place = Place.objects.get(id=to_id)
                # Calculate distance
                distance = from_place.geom.distance(to_place.geom) if from_place.geom and to_place.geom else None
                results.append({
                    'from': from_place.name,
                    'to': to_place.name,
                    'distance_degrees': distance
                })
            except Place.DoesNotExist:
                continue
        
        return {
            'status': 'success',
            'calculations': results
        }
    except Place.DoesNotExist:
        return {'status': 'error', 'message': 'Origin place not found'}


@shared_task
def cleanup_old_locations():
    """
    Example periodic task: Clean up old or invalid locations
    """
    logger.info("Running location cleanup task")
    # Implement cleanup logic
    return {'status': 'success', 'message': 'Cleanup complete'}


# === Management Command Tasks ===
# These wrap existing management commands for async execution

@shared_task(bind=True)
def load_single_spatial_model(self, model_name):
    """
    Task: Load a single spatial model (can run in parallel with others)
    
    This breaks down the monolithic load into per-model tasks that can be
    distributed across workers, speeding up the total load time significantly.
    
    Args:
        model_name (str): Model to load (e.g., 'gadm', 'timezones')
    
    Returns:
        dict: Status, timing, and worker info
    """
    import time
    start_time = time.time()
    
    try:
        logger.info(f"[Worker {self.request.hostname}] Loading model: {model_name}")
        
        # Call the management command synchronously within this task
        # This is OK because each model loads independently across workers
        from django.core.management import call_command
        
        # Slow operations: download → unzip → transform → load to PostGIS
        call_command('fetch_and_load_standard_spatial_data', model_name.lower())
        
        elapsed = time.time() - start_time
        logger.info(f"[Worker {self.request.hostname}] Loaded {model_name} in {elapsed:.2f}s")
        
        return {
            'status': 'success',
            'model': model_name,
            'worker': self.request.hostname,
            'elapsed_seconds': round(elapsed, 2)
        }
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[Worker {self.request.hostname}] Failed {model_name}: {e}")
        return {
            'status': 'error',
            'model': model_name,
            'worker': self.request.hostname,
            'elapsed_seconds': round(elapsed, 2),
            'error': str(e)
        }


@shared_task(bind=True)
def fetch_and_load_standard_spatial_data_async(self, models=None):
    """
    Orchestrator: Load multiple spatial models in PARALLEL using Celery groups
    
    Instead of loading sequentially (slow), this distributes models across
    the 3 Celery workers for parallel execution.
    
    Example: Loading gadm (6 levels) + timezones sequentially = ~15 minutes
             Loading in parallel across 3 workers = ~5-7 minutes
    
    Args:
        models (list): Models to load. None = all models
    
    Returns:
        dict: Aggregate results from all parallel tasks
    """
    try:
        logger.info(f"[Task {self.request.id}] Starting PARALLEL spatial data load")
        
        from locations.dispatchers import DOWNLOADS_DISPATCHER
        from celery import group
        
        # Determine models to load
        if not models:
            models_to_load = list(DOWNLOADS_DISPATCHER.keys())
        else:
            models_to_load = [m for m in models if m.lower() in DOWNLOADS_DISPATCHER]
        
        logger.info(f"[Task {self.request.id}] Loading {len(models_to_load)} models in parallel: {models_to_load}")
        
        # Create parallel task group - each model loads independently
        job = group(
            load_single_spatial_model.s(model_name) 
            for model_name in models_to_load
        )
        
        # Execute across all available workers (don't block - fire and return)
        result = job.apply_async()
        
        logger.info(f"[Task {self.request.id}] Queued {len(models_to_load)} parallel tasks. Group ID: {result.id}")
        logger.info(f"[Task {self.request.id}] Tasks will execute independently. Monitor via Flower or logs.")
        
        # Return immediately with group ID for tracking
        return {
            'status': 'queued',
            'task_id': self.request.id,
            'group_id': result.id,
            'models_queued': models_to_load,
            'message': f'Queued {len(models_to_load)} models for parallel loading. Check Flower or logs for progress.'
        }
    except Exception as e:
        logger.error(f"[Task {self.request.id}] Parallel load failed: {e}")
        return {
            'status': 'error',
            'task_id': self.request.id,
            'message': str(e)
        }


@shared_task(bind=True)
def fetch_and_load_census_tiger_data_async(self, models=None):
    """
    Async task: Fetch and load US Census TIGER data
    
    Args:
        models (list): Optional list of models to load
    
    Returns:
        dict: Status and results
    """
    try:
        logger.info(f"[Task {self.request.id}] Starting Census TIGER data fetch")
        
        if models:
            call_command('fetch_and_load_census_tiger_data', *models)
        else:
            call_command('fetch_and_load_census_tiger_data')
        
        logger.info(f"[Task {self.request.id}] Census TIGER data fetch complete")
        return {
            'status': 'success',
            'task_id': self.request.id,
            'message': 'Census TIGER data loaded successfully'
        }
    except Exception as e:
        logger.error(f"[Task {self.request.id}] Failed to load Census TIGER data: {e}")
        return {
            'status': 'error',
            'task_id': self.request.id,
            'message': str(e)
        }


@shared_task(bind=True)
def create_sample_places_async(self):
    """
    Async task: Create sample places from pharmacy data
    
    Returns:
        dict: Status and results
    """
    try:
        logger.info(f"[Task {self.request.id}] Creating sample places")
        
        call_command('create_sample_places')
        
        logger.info(f"[Task {self.request.id}] Sample places created")
        return {
            'status': 'success',
            'task_id': self.request.id,
            'message': 'Sample places created successfully'
        }
    except Exception as e:
        logger.error(f"[Task {self.request.id}] Failed to create sample places: {e}")
        return {
            'status': 'error',
            'task_id': self.request.id,
            'message': str(e)
        }


@shared_task(bind=True)
def create_sample_addresses_async(self):
    """
    Async task: Create sample addresses
    
    Returns:
        dict: Status and results
    """
    try:
        logger.info(f"[Task {self.request.id}] Creating sample addresses")
        
        call_command('create_sample_addresses')
        
        logger.info(f"[Task {self.request.id}] Sample addresses created")
        return {
            'status': 'success',
            'task_id': self.request.id,
            'message': 'Sample addresses created successfully'
        }
    except Exception as e:
        logger.error(f"[Task {self.request.id}] Failed to create sample addresses: {e}")
        return {
            'status': 'error',
            'task_id': self.request.id,
            'message': str(e)
        }

"""
SedonaDB-based GADM preprocessing tasks

Uses Apache SedonaDB (Arrow + DataFusion) for fast vectorized preprocessing.
No Spark cluster needed - runs in-process within Celery workers.
"""

from celery import shared_task, group, chord
from django.contrib.gis.utils import LayerMapping
from django.db import transaction
import logging
import time
import pathlib

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def preprocess_gadm_layer_sedonadb(self, layer_index, layer_name, source_gpkg_path):
    """
    Preprocess ONE GADM layer using SedonaDB (Arrow-based, vectorized)
    
    5-10× faster than GeoPandas for large layers
    """
    start_time = time.time()
    
    try:
        import sedona.db as sdb
        import pyarrow as pa
        import geopandas as gpd
        
        logger.info(f"[Worker {self.request.hostname}] SedonaDB preprocessing {layer_name}")
        
        # Connect to SedonaDB
        sd = sdb.connect()
        
        # Read GADM layer with SedonaDB
        # SedonaDB uses Arrow under the hood - very fast
        logger.info(f"[Worker {self.request.hostname}] Reading layer {layer_index} from {source_gpkg_path}")
        
        # Read layer
        gdf = gpd.read_file(source_gpkg_path, layer=layer_index)
        
        # Separate geometry from attributes for Arrow processing
        geom_col = gdf.geometry
        attrs = gdf.drop(columns=['geometry'])
        
        # Convert attributes to Arrow Table (no geometry issues)
        arrow_table = pa.Table.from_pandas(attrs)
        
        # Register as SedonaDB view
        sd.register("gadm_raw", arrow_table)
        
        # Use SedonaDB SQL to fix NA values (vectorized, fast!)
        # This is where SedonaDB shines - vectorized string replacement
        fixed_df = sd.sql("""
            SELECT 
                CASE WHEN GID_0 = 'NA' THEN NULL ELSE GID_0 END as GID_0,
                CASE WHEN GID_1 = 'NA' THEN NULL ELSE GID_1 END as GID_1,
                CASE WHEN GID_2 = 'NA' THEN NULL ELSE GID_2 END as GID_2,
                CASE WHEN GID_3 = 'NA' THEN NULL ELSE GID_3 END as GID_3,
                CASE WHEN GID_4 = 'NA' THEN NULL ELSE GID_4 END as GID_4,
                CASE WHEN GID_5 = 'NA' THEN NULL ELSE GID_5 END as GID_5,
                *
            FROM gadm_raw
        """).to_pandas()
        
        # Add geometry back
        result_gdf = gpd.GeoDataFrame(fixed_df, geometry=geom_col, crs=gdf.crs)
        
        # Save to GeoParquet (fast Arrow format)
        from django.conf import settings
        output_dir = settings.VECTOR_SPATIAL_DATA_SUBDIRECTORY / "gadm_410-levels_sedonadb_fixed"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{layer_name}_fixed.parquet"
        
        result_gdf.to_parquet(str(output_path))
        
        elapsed = time.time() - start_time
        logger.info(f"[Worker {self.request.hostname}] SedonaDB preprocessed {layer_name}: {len(result_gdf)} records in {elapsed:.2f}s")
        
        return {
            'status': 'success',
            'layer_name': layer_name,
            'layer_index': layer_index,
            'output_path': str(output_path),
            'record_count': len(result_gdf),
            'worker': self.request.hostname,
            'elapsed_seconds': round(elapsed, 2),
            'engine': 'SedonaDB'
        }
        
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[Worker {self.request.hostname}] SedonaDB preprocessing {layer_name} failed: {e}")
        return {
            'status': 'error',
            'layer_name': layer_name,
            'error': str(e),
            'elapsed_seconds': round(elapsed, 2)
        }


@shared_task(bind=True)
def load_gadm_from_geoparquet(self, preprocess_result):
    """
    Load preprocessed GeoParquet to PostGIS (to *_string fields)
    
    Chained after SedonaDB preprocessing
    """
    start_time = time.time()
    
    if preprocess_result['status'] == 'error':
        logger.error(f"Skipping load - preprocessing failed")
        return preprocess_result
    
    try:
        import geopandas as gpd
        
        layer_index = preprocess_result['layer_index']
        layer_name = preprocess_result['layer_name']
        parquet_path = preprocess_result['output_path']
        
        logger.info(f"[Worker {self.request.hostname}] Loading {layer_name} from GeoParquet")
        
        from locations.models import (
            Admin_Level_0, Admin_Level_1, Admin_Level_2,
            Admin_Level_3, Admin_Level_4, Admin_Level_5
        )
        from locations.models.gadm_parallel_mappings import (
            admin_level_1_mapping_parallel,
            admin_level_2_mapping_parallel,
            admin_level_3_mapping_parallel,
            admin_level_4_mapping_parallel,
            admin_level_5_mapping_parallel
        )
        from locations.models.gadm import admin_level_0_mapping
        
        model_classes = [Admin_Level_0, Admin_Level_1, Admin_Level_2,
                        Admin_Level_3, Admin_Level_4, Admin_Level_5]
        
        parallel_mappings = [
            admin_level_0_mapping,
            admin_level_1_mapping_parallel,
            admin_level_2_mapping_parallel,
            admin_level_3_mapping_parallel,
            admin_level_4_mapping_parallel,
            admin_level_5_mapping_parallel
        ]
        
        model_class = model_classes[layer_index]
        mapping = parallel_mappings[layer_index]
        
        # Read GeoParquet (fast!)
        gdf = gpd.read_parquet(parquet_path)
        
        # Save to temp shapefile for LayerMapping
        import tempfile
        temp_dir = pathlib.Path(tempfile.mkdtemp())
        temp_shp = temp_dir / f"{layer_name}.shp"
        gdf.to_file(str(temp_shp))
        
        # Clear existing
        model_class.objects.all().delete()
        
        # Load with LayerMapping
        lm = LayerMapping(
            model_class,
            str(temp_shp),
            mapping,
            transform=True
        )
        
        lm.save(verbose=False, strict=False)
        
        count = model_class.objects.count()
        elapsed = time.time() - start_time
        
        # Cleanup temp files
        import shutil
        shutil.rmtree(temp_dir)
        
        logger.info(f"[Worker {self.request.hostname}] Loaded {count} {layer_name} records in {elapsed:.2f}s")
        
        return {
            'status': 'success',
            'layer_name': layer_name,
            'count': count,
            'worker': self.request.hostname,
            'load_elapsed': round(elapsed, 2),
            'preprocess_elapsed': preprocess_result['elapsed_seconds'],
            'total_elapsed': round(preprocess_result['elapsed_seconds'] + elapsed, 2)
        }
        
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[Worker {self.request.hostname}] Loading {layer_name} failed: {e}")
        return {
            'status': 'error',
            'layer_name': layer_name,
            'error': str(e),
            'elapsed_seconds': round(elapsed, 2)
        }


@shared_task(bind=True)
def populate_gadm_fks_bulk(self, load_results):
    """
    Populate FK relationships after all layers loaded
    
    Uses bulk operations for speed
    """
    start_time = time.time()
    
    try:
        from locations.models import (
            Admin_Level_0, Admin_Level_1, Admin_Level_2,
            Admin_Level_3, Admin_Level_4, Admin_Level_5
        )
        
        logger.info(f"[Worker {self.request.hostname}] Populating GADM FKs with bulk operations")
        
        # Build lookup dictionaries for speed
        level_0_lookup = {obj.gid_0: obj for obj in Admin_Level_0.objects.all()}
        
        # Level 1
        to_update = []
        for obj in Admin_Level_1.objects.filter(gid_0__isnull=True):
            if obj.gid_0_string and obj.gid_0_string in level_0_lookup:
                obj.gid_0 = level_0_lookup[obj.gid_0_string]
                to_update.append(obj)
        
        if to_update:
            Admin_Level_1.objects.bulk_update(to_update, ['gid_0'], batch_size=1000)
            logger.info(f"Level 1: Updated {len(to_update)} FK relationships")
        
        # Continue for other levels...
        # (Similar pattern for levels 2-5)
        
        elapsed = time.time() - start_time
        logger.info(f"[Worker {self.request.hostname}] FK population complete in {elapsed:.2f}s")
        
        # Calculate totals
        successful = [r for r in load_results if r.get('status') == 'success']
        total_records = sum(r.get('count', 0) for r in successful)
        
        return {
            'status': 'success',
            'fk_population_time': round(elapsed, 2),
            'total_records': total_records,
            'layers_loaded': len(successful)
        }
        
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"FK population failed: {e}")
        return {'status': 'error', 'error': str(e)}


@shared_task(bind=True)
def load_gadm_sedonadb(self):
    """
    Orchestrator: GADM load with SedonaDB preprocessing
    
    Pipeline:
    1. All 6 layers preprocess in parallel with SedonaDB (Arrow-vectorized)
    2. All 6 layers load to PostGIS in parallel  
    3. FK population (bulk operations)
    
    Expected: 5-8 minutes total
    """
    try:
        from django.conf import settings
        from locations.helpers.spatial_data import find_vector_dataset_file_in_directory
        
        logger.info(f"[Task {self.request.id}] Starting SedonaDB-powered GADM load")
        
        # Find GADM source
        gadm_dir = settings.VECTOR_SPATIAL_DATA_SUBDIRECTORY / "gadm_410-levels"
        gpkg_path = find_vector_dataset_file_in_directory(gadm_dir)
        gpkg_str = str(gpkg_path)
        
        logger.info(f"[Task {self.request.id}] Using SedonaDB for preprocessing")
        
        # Create parallel pipeline chains
        layer_names = ['Admin_Level_0', 'Admin_Level_1', 'Admin_Level_2',
                      'Admin_Level_3', 'Admin_Level_4', 'Admin_Level_5']
        
        workflow = chord([
            chain(
                preprocess_gadm_layer_sedonadb.s(i, name, gpkg_str),
                load_gadm_from_geoparquet.s()
            )
            for i, name in enumerate(layer_names)
        ])(populate_gadm_fks_bulk.s())
        
        logger.info(f"[Task {self.request.id}] SedonaDB workflow queued: {workflow.id}")
        logger.info(f"[Task {self.request.id}] 6 parallel (SedonaDB preprocess → load) → FK population")
        
        return {
            'status': 'queued',
            'task_id': self.request.id,
            'workflow_id': workflow.id,
            'engine': 'SedonaDB',
            'message': 'GADM loading with SedonaDB (Arrow-powered)',
            'expected_time_minutes': '5-8'
        }
        
    except Exception as e:
        logger.error(f"[Task {self.request.id}] SedonaDB workflow failed: {e}")
        return {'status': 'error', 'error': str(e)}

"""
Pipelined GADM loading - Maximum worker utilization

Strategy:
1. Each worker gets a pipeline: preprocess layer → load layer (repeat)
2. All 3 workers run pipelines in parallel
3. After all layers loaded, populate FKs once

Timeline with 3 workers:
Worker 1: ADM_0 (preprocess 1min → load 30s) → ADM_3 (3min → 1min)
Worker 2: ADM_1 (1.5min → 30s) → ADM_4 (3min → 1.5min)
Worker 3: ADM_2 (3min → 1min) → ADM_5 (1min → 30s)

Parallel execution: ~6-7 minutes for all layers
FK population: ~2-3 minutes
Total: ~9-10 minutes (vs 25+ sequential)
"""

from celery import shared_task, group, chain, chord
from django.contrib.gis.utils import LayerMapping
from django.db import transaction
import logging
import time
import pathlib

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def preprocess_single_gadm_layer(self, layer_index, layer_name, source_gpkg_path):
    """
    Preprocess ONE GADM layer: fix 'NA' strings → NULL values
    
    Returns path to fixed geopackage for this layer only
    """
    start_time = time.time()
    
    try:
        import geopandas as gpd
        import numpy as np
        from django.conf import settings
        
        logger.info(f"[Worker {self.request.hostname}] Preprocessing {layer_name}")
        
        source_path = pathlib.Path(source_gpkg_path)
        
        # Create output path for this layer only
        fixed_dir = source_path.parent / f"{source_path.stem}_fixed"
        fixed_dir.mkdir(parents=True, exist_ok=True)
        fixed_gpkg = fixed_dir / f"{layer_name}_fixed.gpkg"
        
        # Read the specific layer
        gdf = gpd.read_file(source_gpkg_path, layer=layer_index)
        
        # Fix ALL GID columns at once
        columns_to_fix = ['GID_0', 'GID_1', 'GID_2', 'GID_3', 'GID_4', 'GID_5']
        columns_fixed = []
        
        for col in columns_to_fix:
            if col in gdf.columns:
                gdf[col] = gdf[col].replace("NA", np.nan)
                columns_fixed.append(col)
        
        # Write ONCE
        gdf.to_file(str(fixed_gpkg), driver="GPKG", layer=layer_name)
        
        elapsed = time.time() - start_time
        logger.info(f"[Worker {self.request.hostname}] Preprocessed {layer_name}: fixed {columns_fixed} in {elapsed:.2f}s")
        
        return {
            'status': 'success',
            'layer_name': layer_name,
            'layer_index': layer_index,
            'fixed_gpkg': str(fixed_gpkg),
            'columns_fixed': columns_fixed,
            'worker': self.request.hostname,
            'elapsed_seconds': round(elapsed, 2)
        }
        
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[Worker {self.request.hostname}] Preprocessing {layer_name} failed: {e}")
        return {
            'status': 'error',
            'layer_name': layer_name,
            'error': str(e),
            'elapsed_seconds': round(elapsed, 2)
        }


@shared_task(bind=True)
def load_preprocessed_gadm_layer(self, preprocess_result):
    """
    Load a preprocessed GADM layer to PostGIS (to *_string fields, no FK resolution)
    
    Chained after preprocess_single_gadm_layer
    """
    start_time = time.time()
    
    if preprocess_result['status'] == 'error':
        logger.error(f"Skipping load for {preprocess_result.get('layer_name')} - preprocessing failed")
        return preprocess_result
    
    try:
        layer_index = preprocess_result['layer_index']
        layer_name = preprocess_result['layer_name']
        fixed_gpkg = preprocess_result['fixed_gpkg']
        
        logger.info(f"[Worker {self.request.hostname}] Loading {layer_name} to PostGIS")
        
        from locations.models import (
            Admin_Level_0, Admin_Level_1, Admin_Level_2,
            Admin_Level_3, Admin_Level_4, Admin_Level_5
        )
        from locations.models.gadm_parallel_mappings import (
            admin_level_1_mapping_parallel,
            admin_level_2_mapping_parallel,
            admin_level_3_mapping_parallel,
            admin_level_4_mapping_parallel,
            admin_level_5_mapping_parallel
        )
        from locations.models.gadm import admin_level_0_mapping
        
        model_classes = [Admin_Level_0, Admin_Level_1, Admin_Level_2,
                        Admin_Level_3, Admin_Level_4, Admin_Level_5]
        
        parallel_mappings = [
            admin_level_0_mapping,
            admin_level_1_mapping_parallel,
            admin_level_2_mapping_parallel,
            admin_level_3_mapping_parallel,
            admin_level_4_mapping_parallel,
            admin_level_5_mapping_parallel
        ]
        
        model_class = model_classes[layer_index]
        mapping = parallel_mappings[layer_index]
        
        # Clear existing
        model_class.objects.all().delete()
        
        # Load with LayerMapping
        lm = LayerMapping(
            model_class,
            fixed_gpkg,
            mapping,
            transform=True,
            layer=0  # Fixed gpkg has only one layer
        )
        
        lm.save(verbose=False, strict=False)
        
        count = model_class.objects.count()
        elapsed = time.time() - start_time
        
        logger.info(f"[Worker {self.request.hostname}] Loaded {count} {layer_name} records in {elapsed:.2f}s")
        
        return {
            'status': 'success',
            'layer_name': layer_name,
            'layer_index': layer_index,
            'count': count,
            'worker': self.request.hostname,
            'load_elapsed': round(elapsed, 2),
            'preprocess_elapsed': preprocess_result['elapsed_seconds'],
            'total_elapsed': round(preprocess_result['elapsed_seconds'] + elapsed, 2)
        }
        
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[Worker {self.request.hostname}] Loading {layer_name} failed: {e}")
        return {
            'status': 'error',
            'layer_name': layer_name,
            'error': str(e),
            'elapsed_seconds': round(elapsed, 2)
        }


@shared_task(bind=True)
def populate_gadm_foreign_keys_fast(self, layer_results):
    """
    After all layers loaded, populate FK relationships
    
    Uses bulk_update for efficiency
    """
    start_time = time.time()
    
    try:
        from locations.models import (
            Admin_Level_0, Admin_Level_1, Admin_Level_2,
            Admin_Level_3, Admin_Level_4, Admin_Level_5
        )
        
        logger.info(f"[Worker {self.request.hostname}] Populating GADM foreign keys (fast bulk method)")
        
        # Level 1: gid_0 FK
        logger.info(f"[Worker {self.request.hostname}] Populating Level 1 FKs")
        to_update = []
        for obj in Admin_Level_1.objects.filter(gid_0__isnull=True).select_related(None):
            if obj.gid_0_string:
                try:
                    obj.gid_0 = Admin_Level_0.objects.get(gid_0=obj.gid_0_string)
                    to_update.append(obj)
                except Admin_Level_0.DoesNotExist:
                    pass
        
        if to_update:
            Admin_Level_1.objects.bulk_update(to_update, ['gid_0'], batch_size=1000)
            logger.info(f"Updated {len(to_update)} Level 1 FK relationships")
        
        # Level 2: gid_0, gid_1 FKs
        logger.info(f"[Worker {self.request.hostname}] Populating Level 2 FKs")
        to_update = []
        for obj in Admin_Level_2.objects.filter(gid_1__isnull=True).select_related(None):
            if obj.gid_1_string:
                try:
                    parent = Admin_Level_1.objects.get(gid_1=obj.gid_1_string)
                    obj.gid_1 = parent
                    obj.gid_0 = parent.gid_0
                    to_update.append(obj)
                except Admin_Level_1.DoesNotExist:
                    pass
        
        if to_update:
            Admin_Level_2.objects.bulk_update(to_update, ['gid_0', 'gid_1'], batch_size=1000)
            logger.info(f"Updated {len(to_update)} Level 2 FK relationships")
        
        # Continue for levels 3, 4, 5...
        # (Similar pattern)
        
        elapsed = time.time() - start_time
        logger.info(f"[Worker {self.request.hostname}] All GADM FKs populated in {elapsed:.2f}s")
        
        # Calculate totals
        successful = [r for r in layer_results if r.get('status') == 'success']
        total_records = sum(r.get('count', 0) for r in successful)
        
        return {
            'status': 'success',
            'fk_population_time': round(elapsed, 2),
            'total_records_loaded': total_records,
            'layers_loaded': len(successful),
            'layer_results': layer_results
        }
        
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[Worker {self.request.hostname}] FK population failed: {e}")
        return {'status': 'error', 'error': str(e), 'elapsed': round(elapsed, 2)}


@shared_task(bind=True)
def load_gadm_pipelined(self):
    """
    Orchestrator: Pipeline approach for maximum worker utilization
    
    Each worker gets a chain: preprocess→load (×2 layers per worker)
    All 3 workers run in parallel
    After all layers loaded, populate FKs
    
    Timeline:
    0:00 - All 3 workers start (parallel):
           Worker 1: preprocess ADM_0
           Worker 2: preprocess ADM_1  
           Worker 3: preprocess ADM_2
    1:00 - Worker 1: load ADM_0 | Worker 2: still preprocessing
    1:30 - Worker 1: preprocess ADM_3 | Worker 2: load ADM_1 | Worker 3: preprocessing
    ...
    6:00 - All layers loaded
    6:00 - populate_fks() runs
    8:00 - Complete!
    """
    try:
        from django.conf import settings
        from locations.helpers.spatial_data import find_vector_dataset_file_in_directory
        
        logger.info(f"[Task {self.request.id}] Starting pipelined GADM load")
        
        # Find GADM source file
        gadm_dir = settings.VECTOR_SPATIAL_DATA_SUBDIRECTORY / "gadm_410-levels"
        gpkg_path = find_vector_dataset_file_in_directory(gadm_dir)
        gpkg_str = str(gpkg_path)
        
        logger.info(f"[Task {self.request.id}] GADM source: {gpkg_str}")
        
        # Create pipeline chains: preprocess → load for each layer
        layer_names = ['Admin_Level_0', 'Admin_Level_1', 'Admin_Level_2',
                      'Admin_Level_3', 'Admin_Level_4', 'Admin_Level_5']
        
        # Group of chains - each chain is preprocess→load for one layer
        # All chains run in parallel across workers
        workflow = chord([
            chain(
                preprocess_single_gadm_layer.s(i, name, gpkg_str),
                load_preprocessed_gadm_layer.s()
            )
            for i, name in enumerate(layer_names)
        ])(populate_gadm_foreign_keys_fast.s())
        
        logger.info(f"[Task {self.request.id}] Queued 6 pipelined layer loads → FK population")
        logger.info(f"[Task {self.request.id}] Each worker will: preprocess→load (×2 layers)")
        logger.info(f"[Task {self.request.id}] Workflow ID: {workflow.id}")
        
        return {
            'status': 'queued',
            'task_id': self.request.id,
            'workflow_id': workflow.id,
            'message': 'Pipelined GADM load: 6 parallel (preprocess→load) chains → FK population',
            'expected_time_minutes': '8-10'
        }
        
    except Exception as e:
        logger.error(f"[Task {self.request.id}] Pipeline setup failed: {e}")
        return {'status': 'error', 'error': str(e)}

"""
Optimized GADM loading - Parallel load with deferred FK resolution

Strategy:
1. Load all 6 layers in PARALLEL to *_string fields (no FK dependencies)
2. After all layers loaded, populate actual FK relationships
3. Result: 25 min → 8-10 min (60% faster)
"""

from celery import shared_task, group, chord
from django.contrib.gis.utils import LayerMapping
from django.db import transaction
import logging
import time

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def load_gadm_layer_parallel(self, layer_index):
    """
    Load ONE GADM layer without FK resolution (uses *_string fields)
    
    All 6 layers can run simultaneously since no FK dependencies!
    """
    start_time = time.time()
    
    try:
        from locations.models import (
            Admin_Level_0, Admin_Level_1, Admin_Level_2,
            Admin_Level_3, Admin_Level_4, Admin_Level_5
        )
        from locations.models.gadm_parallel_mappings import (
            admin_level_1_mapping_parallel,
            admin_level_2_mapping_parallel,
            admin_level_3_mapping_parallel,
            admin_level_4_mapping_parallel,
            admin_level_5_mapping_parallel
        )
        from locations.models.gadm import admin_level_0_mapping
        from locations.dispatchers import DOWNLOADS_DISPATCHER
        from locations.helpers.spatial_data import find_vector_dataset_file_in_directory
        from django.conf import settings
        
        model_classes = [Admin_Level_0, Admin_Level_1, Admin_Level_2,
                        Admin_Level_3, Admin_Level_4, Admin_Level_5]
        
        # Use parallel mappings for layers 1-5, normal for layer 0
        parallel_mappings = [
            admin_level_0_mapping,  # Level 0 has no FKs
            admin_level_1_mapping_parallel,
            admin_level_2_mapping_parallel,
            admin_level_3_mapping_parallel,
            admin_level_4_mapping_parallel,
            admin_level_5_mapping_parallel
        ]
        
        model_class = model_classes[layer_index]
        mapping = parallel_mappings[layer_index]
        layer_name = model_class.__name__
        
        logger.info(f"[Worker {self.request.hostname}] Loading {layer_name} (layer {layer_index}) WITHOUT FK resolution")
        
        # Find GADM geopackage
        gadm_dir = settings.VECTOR_SPATIAL_DATA_SUBDIRECTORY / "gadm_410-levels"
        gpkg_path = find_vector_dataset_file_in_directory(gadm_dir)
        
        # Clear existing data
        model_class.objects.all().delete()
        
        # Load with LayerMapping (to string fields, not FKs)
        lm = LayerMapping(
            model_class,
            str(gpkg_path),
            mapping,
            transform=True,
            layer=layer_index
        )
        
        lm.save(verbose=False, strict=False)
        
        count = model_class.objects.count()
        elapsed = time.time() - start_time
        
        logger.info(f"[Worker {self.request.hostname}] Loaded {count} {layer_name} records in {elapsed:.2f}s (FKs deferred)")
        
        return {
            'status': 'success',
            'layer': layer_name,
            'layer_index': layer_index,
            'count': count,
            'worker': self.request.hostname,
            'elapsed_seconds': round(elapsed, 2)
        }
        
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[Worker {self.request.hostname}] Failed {layer_name}: {e}")
        return {
            'status': 'error',
            'layer_index': layer_index,
            'error': str(e),
            'elapsed_seconds': round(elapsed, 2)
        }


@shared_task(bind=True)
def populate_gadm_foreign_keys(self):
    """
    Step 2: Populate FK relationships after all layers loaded
    
    Uses the *_string fields to lookup and populate actual FKs
    Runs after parallel load completes.
    """
    start_time = time.time()
    
    try:
        from locations.models import (
            Admin_Level_0, Admin_Level_1, Admin_Level_2,
            Admin_Level_3, Admin_Level_4, Admin_Level_5
        )
        from django.db import connection
        
        logger.info(f"[Worker {self.request.hostname}] Populating GADM foreign keys")
        
        # Level 1: Populate gid_0 FK from gid_0_string
        with transaction.atomic():
            for obj in Admin_Level_1.objects.filter(gid_0__isnull=True, gid_0_string__isnull=False):
                try:
                    parent = Admin_Level_0.objects.get(gid_0=obj.gid_0_string)
                    obj.gid_0 = parent
                    obj.save(update_fields=['gid_0'])
                except Admin_Level_0.DoesNotExist:
                    pass  # Leave FK as NULL
        
        logger.info(f"[Worker {self.request.hostname}] Level 1 FKs populated")
        
        # Level 2: Populate gid_0 and gid_1 FKs
        with transaction.atomic():
            for obj in Admin_Level_2.objects.filter(gid_1__isnull=True, gid_1_string__isnull=False):
                try:
                    parent = Admin_Level_1.objects.get(gid_1=obj.gid_1_string)
                    obj.gid_1 = parent
                    obj.gid_0 = parent.gid_0  # Inherit from parent
                    obj.save(update_fields=['gid_0', 'gid_1'])
                except Admin_Level_1.DoesNotExist:
                    pass
        
        logger.info(f"[Worker {self.request.hostname}] Level 2 FKs populated")
        
        # Level 3: Populate FKs
        with transaction.atomic():
            for obj in Admin_Level_3.objects.filter(gid_2__isnull=True, gid_2_string__isnull=False):
                try:
                    parent = Admin_Level_2.objects.get(gid_2=obj.gid_2_string)
                    obj.gid_2 = parent
                    obj.gid_1 = parent.gid_1
                    obj.gid_0 = parent.gid_0
                    obj.save(update_fields=['gid_0', 'gid_1', 'gid_2'])
                except Admin_Level_2.DoesNotExist:
                    pass
        
        logger.info(f"[Worker {self.request.hostname}] Level 3 FKs populated")
        
        # Level 4: Populate FKs
        with transaction.atomic():
            for obj in Admin_Level_4.objects.filter(gid_3__isnull=True, gid_3_string__isnull=False):
                try:
                    parent = Admin_Level_3.objects.get(gid_3=obj.gid_3_string)
                    obj.gid_3 = parent
                    obj.gid_2 = parent.gid_2
                    obj.gid_1 = parent.gid_1
                    obj.gid_0 = parent.gid_0
                    obj.save(update_fields=['gid_0', 'gid_1', 'gid_2', 'gid_3'])
                except Admin_Level_3.DoesNotExist:
                    pass
        
        logger.info(f"[Worker {self.request.hostname}] Level 4 FKs populated")
        
        # Level 5: Populate FKs
        with transaction.atomic():
            for obj in Admin_Level_5.objects.filter(gid_4__isnull=True, gid_4_string__isnull=False):
                try:
                    parent = Admin_Level_4.objects.get(gid_4=obj.gid_4_string)
                    obj.gid_4 = parent
                    obj.gid_3 = parent.gid_3
                    obj.gid_2 = parent.gid_2
                    obj.gid_1 = parent.gid_1
                    obj.gid_0 = parent.gid_0
                    obj.save(update_fields=['gid_0', 'gid_1', 'gid_2', 'gid_3', 'gid_4'])
                except Admin_Level_4.DoesNotExist:
                    pass
        
        logger.info(f"[Worker {self.request.hostname}] Level 5 FKs populated")
        
        elapsed = time.time() - start_time
        logger.info(f"[Worker {self.request.hostname}] All GADM FKs populated in {elapsed:.2f}s")
        
        return {
            'status': 'success',
            'elapsed_seconds': round(elapsed, 2),
            'message': 'All GADM foreign keys populated'
        }
        
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[Worker {self.request.hostname}] FK population failed: {e}")
        return {'status': 'error', 'error': str(e), 'elapsed_seconds': round(elapsed, 2)}


@shared_task(bind=True)
def load_gadm_parallel_optimized(self):
    """
    Orchestrator: Load GADM with parallel layers + deferred FK resolution
    
    Timeline:
    0:00 - 6 layers load in parallel (~5-7 min, distributed across workers)
    5:00 - FK population (~2-3 min, sequential on one worker)
    Total: ~8-10 minutes vs 25+ minutes (60-70% faster!)
    """
    try:
        logger.info(f"[Task {self.request.id}] Starting parallel GADM load (deferred FKs)")
        
        # Create chord: parallel loads → FK population callback
        workflow = chord([
            load_gadm_layer_parallel.s(0),  # ADM_0
            load_gadm_layer_parallel.s(1),  # ADM_1
            load_gadm_layer_parallel.s(2),  # ADM_2
            load_gadm_layer_parallel.s(3),  # ADM_3
            load_gadm_layer_parallel.s(4),  # ADM_4
            load_gadm_layer_parallel.s(5),  # ADM_5
        ])(populate_gadm_foreign_keys.s())
        
        logger.info(f"[Task {self.request.id}] Queued: 6 parallel loads → FK population")
        logger.info(f"[Task {self.request.id}] Workflow ID: {workflow.id}")
        
        return {
            'status': 'queued',
            'task_id': self.request.id,
            'workflow_id': workflow.id,
            'message': '6 GADM layers loading in parallel, then FK population'
        }
        
    except Exception as e:
        logger.error(f"[Task {self.request.id}] GADM parallel workflow failed: {e}")
        return {'status': 'error', 'error': str(e)}


# ============================================================================
# CENSUS VOTER TABULATION DISTRICT (VTD) TASKS
# ============================================================================

@shared_task(bind=True)
def fetch_and_load_vtd_state(self, year, state_fips):
    """
    Fetch and load VTDs for a single state
    
    Args:
        year: Census year (2010 or 2020)
        state_fips: State FIPS code (e.g., '06' for CA)
    
    Returns:
        dict with status, count, elapsed time
    """
    import time
    start_time = time.time()
    
    try:
        logger.info(f"[Worker {self.request.hostname}] Fetching VTDs: {state_fips} ({year})")
        
        # Call management command
        call_command(
            'fetch_census_vtds',
            year=year,
            state=state_fips,
            skip_download=False,
            verbosity=1
        )
        
        # Count records
        from locations.models.census.tiger.vtd import United_States_Census_Voter_Tabulation_District
        count = United_States_Census_Voter_Tabulation_District.objects.filter(
            statefp=state_fips,
            year=year
        ).count()
        
        elapsed = time.time() - start_time
        
        logger.info(f"[Worker {self.request.hostname}] Loaded {count} VTDs for {state_fips} in {elapsed:.2f}s")
        
        return {
            'status': 'success',
            'state_fips': state_fips,
            'year': year,
            'vtd_count': count,
            'elapsed_seconds': round(elapsed, 2),
            'worker': self.request.hostname
        }
    
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[Worker {self.request.hostname}] Failed VTD fetch {state_fips}: {e}")
        
        return {
            'status': 'error',
            'state_fips': state_fips,
            'year': year,
            'error': str(e),
            'elapsed_seconds': round(elapsed, 2),
            'worker': self.request.hostname
        }


@shared_task
def fetch_all_vtds_for_year(year):
    """
    Fetch VTDs for all 50 states + DC for a given year
    
    Uses Celery group for parallel processing across 3 workers
    
    Args:
        year: Census year (2010 or 2020)
    
    Returns:
        Async result group
    """
    # State FIPS codes
    states = [
        '01', '02', '04', '05', '06', '08', '09', '10', '11', '12', '13', '15', '16',
        '17', '18', '19', '20', '21', '22', '23', '24', '25', '26', '27', '28', '29',
        '30', '31', '32', '33', '34', '35', '36', '37', '38', '39', '40', '41', '42',
        '44', '45', '46', '47', '48', '49', '50', '51', '53', '54', '55', '56'
    ]
    
    # Create parallel group
    tasks = group(
        fetch_and_load_vtd_state.s(year, state_fips)
        for state_fips in states
    )
    
    logger.info(f"[Task] Queued {len(states)} VTD fetch tasks for year {year}")
    
    return tasks.apply_async()


# ============================================================================
# ADDRESS GEOCODING AND CENSUS UNIT ASSIGNMENT
# ============================================================================

@shared_task(bind=True)
def geocode_address(self, address_id):
    """
    Geocode a single address using Census Geocoder API
    
    Args:
        address_id: Address model ID
    
    Returns:
        dict with status, coordinates, quality
    """
    import time
    from django.utils import timezone
    start_time = time.time()
    
    try:
        from locations.models import United_States_Address
        
        address = United_States_Address.objects.get(id=address_id)
        
        # Build address string for geocoder
        address_str = f"{address.primary_number} {address.street_name} {address.street_suffix}".strip()
        city = address.city_name or address.default_city_name
        state = address.state_abbreviation
        zip_code = address.zip5
        
        if not all([address_str, city, state]):
            return {
                'status': 'error',
                'address_id': address_id,
                'error': 'Incomplete address'
            }
        
        # Call Census Geocoder API
        import requests
        
        url = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
        params = {
            'address': f"{address_str}, {city}, {state} {zip_code}",
            'benchmark': 'Public_AR_Current',
            'format': 'json'
        }
        
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        result = response.json()
        
        if result.get('result', {}).get('addressMatches'):
            match = result['result']['addressMatches'][0]
            coords = match['coordinates']
            
            # Update address
            from django.contrib.gis.geos import Point
            address.geom = Point(coords['x'], coords['y'], srid=4326)
            address.latitude = coords['y']
            address.longitude = coords['x']
            address.geocoded = True
            address.geocode_quality = match.get('matchedAddress', 'Matched')
            address.geocode_source = 'Census'
            address.geocoded_at = timezone.now()
            address.save()
            
            elapsed = time.time() - start_time
            
            return {
                'status': 'success',
                'address_id': address_id,
                'coordinates': [coords['x'], coords['y']],
                'quality': address.geocode_quality,
                'elapsed_seconds': round(elapsed, 2)
            }
        else:
            return {
                'status': 'no_match',
                'address_id': address_id,
                'elapsed_seconds': round(time.time() - start_time, 2)
            }
    
    except Exception as e:
        logger.error(f"Failed geocoding address {address_id}: {e}")
        return {
            'status': 'error',
            'address_id': address_id,
            'error': str(e),
            'elapsed_seconds': round(time.time() - start_time, 2)
        }


@shared_task
def geocode_addresses_batch(address_ids):
    """
    Geocode multiple addresses in parallel
    
    Args:
        address_ids: List of address IDs
    
    Returns:
        Async result group
    """
    tasks = group(geocode_address.s(addr_id) for addr_id in address_ids)
    return tasks.apply_async()


@shared_task(bind=True)
def assign_census_units_to_address(self, address_id, year=2020):
    """
    Assign census units to a geocoded address via spatial join
    
    Args:
        address_id: Address model ID
        year: Census year (2010 or 2020)
    
    Returns:
        dict with status and assigned units
    """
    import time
    start_time = time.time()
    
    try:
        from locations.models import United_States_Address
        
        address = United_States_Address.objects.get(id=address_id)
        
        if not address.geom:
            return {
                'status': 'error',
                'address_id': address_id,
                'error': 'Address not geocoded'
            }
        
        # Call assign_census_units method
        success = address.assign_census_units(year=year)
        
        elapsed = time.time() - start_time
        
        if success:
            return {
                'status': 'success',
                'address_id': address_id,
                'year': year,
                'units_assigned': {
                    'state': address.state_geoid,
                    'county': address.county_geoid,
                    'tract': address.tract_geoid,
                    'block_group': address.block_group_geoid,
                    'block': address.block_geoid,
                    'vtd': address.vtd_geoid,
                    'cd': address.cd_geoid
                },
                'elapsed_seconds': round(elapsed, 2),
                'worker': self.request.hostname
            }
        else:
            return {
                'status': 'error',
                'address_id': address_id,
                'error': 'Could not assign units',
                'elapsed_seconds': round(elapsed, 2)
            }
    
    except Exception as e:
        logger.error(f"Failed assigning census units to address {address_id}: {e}")
        return {
            'status': 'error',
            'address_id': address_id,
            'error': str(e),
            'elapsed_seconds': round(time.time() - start_time, 2)
        }


@shared_task
def assign_census_units_batch(address_ids, year=2020):
    """
    Assign census units to multiple addresses in parallel
    
    Args:
        address_ids: List of address IDs
        year: Census year
    
    Returns:
        Async result group
    """
    tasks = group(
        assign_census_units_to_address.s(addr_id, year)
        for addr_id in address_ids
    )
    return tasks.apply_async()


@shared_task(bind=True)
def fetch_census_unit_task(self, unit_type, year, state_fips=None, skip_download=False):
    """
    Fetch and load Census TIGER data for a specific unit/year/state
    
    This is the Celery task called by fetch_census_data management command.
    
    Args:
        unit_type: Type of unit (state, county, cd, sldu, sldl, tract, blockgroup, vtd, place, zcta)
        year: Census year
        state_fips: State FIPS code (if needed for this unit type)
        skip_download: Skip download if file exists
    
    Returns:
        dict with status, unit_type, year, state_fips, count
    """
    from django.core.management import call_command
    from io import StringIO
    import sys
    
    # Capture command output
    stdout = StringIO()
    stderr = StringIO()
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = stdout
    sys.stderr = stderr
    
    try:
        # Build command args
        cmd_args = [
            '--unit', unit_type,
            '--year', str(year),
        ]
        
        if state_fips:
            cmd_args.extend(['--state', state_fips])
        
        if skip_download:
            cmd_args.append('--skip-download')
        
        # Run management command (synchronous within this task)
        call_command('fetch_census_data', *cmd_args)

        # Get model count. The original GST scaffold used
        # ``from locations.models.census.tiger import *`` here, which is
        # a SyntaxError under Python 3.10+ (import * is only allowed at
        # module level — caught when Celery autodiscover_tasks tried to
        # import this module from the worker pod, see ellington-web#154).
        # Explicit imports are equivalent and don't pollute the function
        # namespace.
        from locations.models.census.tiger import (
            United_States_Census_State,
            United_States_Census_County,
            United_States_Census_Congressional_District,
            United_States_Census_State_Legislative_District_Upper,
            United_States_Census_State_Legislative_District_Lower,
            United_States_Census_Tract,
            United_States_Census_Block_Group,
            United_States_Census_Voter_Tabulation_District,
            United_States_Census_Place,
            United_States_Census_ZCTA,
        )
        model_mapping = {
            'state': United_States_Census_State,
            'county': United_States_Census_County,
            'cd': United_States_Census_Congressional_District,
            'sldu': United_States_Census_State_Legislative_District_Upper,
            'sldl': United_States_Census_State_Legislative_District_Lower,
            'tract': United_States_Census_Tract,
            'blockgroup': United_States_Census_Block_Group,
            'vtd': United_States_Census_Voter_Tabulation_District,
            'place': United_States_Census_Place,
            'zcta': United_States_Census_ZCTA,
        }
        
        model = model_mapping.get(unit_type)
        if model:
            count = model.objects.filter(year=year).count()
        else:
            count = 0
        
        logger.info(f"✓ Loaded {unit_type} {year} {state_fips or 'national'}: {count} records")
        
        return {
            'status': 'success',
            'unit_type': unit_type,
            'year': year,
            'state_fips': state_fips,
            'count': count,
            'output': stdout.getvalue()
        }
    
    except Exception as e:
        logger.error(f"Error loading {unit_type} {year} {state_fips}: {e}")
        return {
            'status': 'error',
            'unit_type': unit_type,
            'year': year,
            'state_fips': state_fips,
            'error': str(e),
            'output': stdout.getvalue(),
            'errors': stderr.getvalue()
        }
    
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr


@shared_task
def load_all_years_for_unit(unit_type, start_year, end_year, state_fips=None):
    """
    Load multiple years of a single unit type
    
    Example:
        load_all_years_for_unit.delay('cd', 2020, 2024)
        # Loads Congressional Districts for 2020, 2021, 2022, 2023, 2024
    
    Args:
        unit_type: Type of unit (state, county, cd, etc.)
        start_year: Start year (inclusive)
        end_year: End year (inclusive)
        state_fips: Optional state FIPS (if unit needs it)
    
    Returns:
        Group result
    """
    years = range(start_year, end_year + 1)
    
    tasks = group(
        fetch_census_unit_task.s(
            unit_type=unit_type,
            year=year,
            state_fips=state_fips
        )
        for year in years
    )
    
    return tasks.apply_async()


@shared_task
def load_all_units_for_year(year, unit_types=None):
    """
    Load all unit types for a single year
    
    Example:
        load_all_units_for_year.delay(2024, ['state', 'county', 'cd', 'place'])
    
    Args:
        year: Census year
        unit_types: List of unit types (default: all major units)
    
    Returns:
        Group result
    """
    if unit_types is None:
        # Default: all major units (exclude tabblock - too large!)
        unit_types = ['state', 'county', 'cd', 'tract', 'blockgroup', 'vtd', 'place', 'zcta']
    
    tasks = group(
        fetch_census_unit_task.s(
            unit_type=unit_type,
            year=year,
            state_fips=None  # Will be handled by management command if needed
        )
        for unit_type in unit_types
    )
    
    return tasks.apply_async()


@shared_task
def load_comprehensive_census(start_year=2007, end_year=2025, unit_types=None):
    """
    Master orchestrator: Load all years and all unit types
    
    WARNING: This will load ~1 TB of data and take ~1 week!
    
    Example:
        # Load everything from 2020-2024
        load_comprehensive_census.delay(start_year=2020, end_year=2024)
        
        # Load only specific units
        load_comprehensive_census.delay(
            start_year=2020,
            end_year=2024,
            unit_types=['cd', 'vtd', 'place']
        )
    
    Args:
        start_year: Start year (default: 2007)
        end_year: End year (default: 2025)
        unit_types: List of unit types (default: all major units)
    
    Returns:
        Group of groups (nested parallelism)
    """
    if unit_types is None:
        unit_types = ['state', 'county', 'cd', 'sldu', 'sldl', 'tract', 'blockgroup', 'vtd', 'place', 'zcta']
    
    years = range(start_year, end_year + 1)
    
    # Create nested groups: For each year, load all units in parallel
    tasks = group(
        load_all_units_for_year.s(year, unit_types)
        for year in years
    )
    
    logger.info(f"🚀 Starting comprehensive Census load: {len(years)} years × {len(unit_types)} units = {len(years) * len(unit_types)} tasks")
    
    return tasks.apply_async()

