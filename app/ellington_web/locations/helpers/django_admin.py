"""
Locations-coupled ORM helpers. These import from locations.models so they
have to live inside the app, not in siege_utilities.
"""

import logging
import random

from django.db.models import Max

from locations.models import United_States_Address

logger = logging.getLogger("django")


def get_random_object(django_model):
    """Pick a random object from a Django model's table by random PK lookup."""
    max_id = django_model.objects.all().aggregate(max_id=Max("id"))["max_id"]
    while True:
        pk = random.randint(1, max_id)
        target_object = django_model.objects.filter(pk=pk).first()
        if target_object:
            return target_object


def create_united_states_address(
    primary_number,
    street_name,
    city_name,
    state_abbreviation,
    zip5,
    longitude=None,
    latitude=None,
):
    """Create and save a United_States_Address with the given fields."""
    simple_address = (
        f"{primary_number}; {street_name} ;{city_name} ;{state_abbreviation} "
        f";{zip5} ; {longitude} ; {latitude}"
    )
    logger.info(f"Trying to create an address for {simple_address}")

    try:
        us_address = United_States_Address(
            primary_number=primary_number,
            street_name=street_name,
            city_name=city_name,
            state_abbreviation=state_abbreviation,
            zip5=zip5,
            longitude=longitude,
            latitude=latitude,
        )
        us_address.save()
        logger.info(f"Successfully created an address for {simple_address}")
        return us_address
    except Exception as e:
        logger.error(f"Failed to create an address for {simple_address}: {e}")
        return False


def update_model_fields_to_single_value(
    target_model, fields_to_update, existing_value, intended_value
):
    """Bulk-update named fields from an existing value to an intended value."""
    for field in fields_to_update:
        try:
            target_objects = target_model.objects.filter(field=existing_value)
            target_objects.update(field=intended_value).update(field=None)
        except Exception as e:
            logger.error(f"Failed to update {field} for {target_model}: {e}")


def update_model_geometry_foreign_keys(target_object, model_keys_and_names):
    """
    Update spatial-FK fields on a GeoDjango object via geometry intersection.
    Assumes geometry columns are named 'geom' (OSGeo convention).
    """
    target_object_fields = [
        field.name for field in target_object._meta.get_fields(include_parents=True)
    ]
    keys_to_test = [
        tof for tof in target_object_fields if tof in model_keys_and_names.keys()
    ]

    for k in keys_to_test:
        foreign_model = model_keys_and_names[k]
        try:
            foreign_geom_object = foreign_model.objects.get(
                geom__intersects=target_object.geom
            )
            setattr(target_object, k, foreign_geom_object)
        except Exception:
            setattr(target_object, k, None)

    return target_object
