# Imports
# Generic Python Library Imports

import sys, os
import pathlib
import csv
from django.db.models import Q

# Django Management Command Imports

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

# custom functions and data

from locations.helpers.geocoding import geocode_with_nominatim_public
from locations.models import *

# logging

import logging

logger = logging.getLogger("django")


class Command(BaseCommand):
    args = ""
    help = "Creates US Address objects from Crime data and uses the Nominatim API to geocode them"

    def handle(self, *args, **kwargs):

        # get command line specified options
        # container variables

        successes = []
        failures = []

        # specify which models to work on
        # if the user specifies nothing, do them all

        SAMPLE_ADDRESSES_CSV = settings.TABULAR_DATA_SUBDIRECTORY / "address-sample.csv"

        # start work
        try:
            message = "\n"
            message += "About to do the business"

            # result = create_addresses_from_data_file(
            #     path_to_data_file=SAMPLE_ADDRESSES_CSV
            # )
            #
            # successes.append(result)

            result = geocode_addresses_with_nominatim()

            successes.append(result)

        except Exception as e:
            message = "\n"
            message += f"There was an error at the management command level working on {message}: {e}"
            logger.error(message)
            failures.append(message)

        # count failures
        if len(failures) > 0:
            message = "\n FAILURE"
            message += f"\n The following models succeeded : {successes}"
            message += f"\n The following models failed : {failures}"

            logger.error(message)

        else:
            message = "\n SUCCESS"
            message += f"\n The following models succeeded : {successes}"
            message += f"\n The following models failed : {failures}"

            logger.info(message)


def create_addresses_from_data_file(path_to_data_file: pathlib.Path) -> bool:

    # container for bad addresses

    bad_addresses = []
    United_States_Address.objects.all().delete()

    # open the csv and create a DictReader

    try:
        inpath = pathlib.Path(path_to_data_file)

        with inpath.open("r", newline="\n", encoding="utf-8-sig") as infile:
            reader = csv.DictReader(infile)
            for row in reader:

                # create concatenated street name

                street_name_fields = [
                    row["predir"],
                    row["prequal"],
                    row["pretyp"],
                    row["street"],
                    row["suftyp"],
                    row["sufqual"],
                    row["sufdir"],
                ]

                concatenated_street_name = " ".join(street_name_fields)

                us_address = United_States_Address(
                    primary_number=row["number"],
                    street_name=concatenated_street_name,
                    city_name=row["city"],
                    state_abbreviation=row["state"],
                    zip5=row["zip"],
                )
                us_address.save()

        message = "\n"
        message += "Success creating address objects"
        logger.info(message)
        return True

    except Exception as e:
        message = "\n"
        message += f"There was an error creating address objects: {e}"
        logger.error(message)
        return False


def geocode_addresses_with_nominatim() -> bool:

    ungeocoded_addresses = United_States_Address.objects.filter(
        (Q(latitude=None) | Q(longitude=None))
    )

    for uga in ungeocoded_addresses:

        concatenated_street_address = (
            f"{uga.primary_number} {uga.street_name} {uga.street_suffix}"
        )

        concatenated_address = f"{concatenated_street_address}, {uga.city_name}, {uga.state_abbreviation} {uga.zip5}".replace(
            "  ", " "
        )

        address_information_from_nominatim = geocode_with_nominatim_public(
            concatenated_address=concatenated_address
        )

        if address_information_from_nominatim:
            try:
                uga.latitude = uga[settings.NOMINATIM_LATITUDE_VARIABLE]
                uga.longitude = uga[settings.NOMINATIM_LONGITUDE_VARIABLE]
                uga.save()

            except Exception as e:
                message = ""
                message += f"There was an error updating address {uga}: {e}"
                logger.error(message)
                return False

    return True
