# Imports
import pathlib

# Django Management Command Imports

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

# Generic Python Library Imports

import sys, os

# custom functions and data

# logging

import logging

logger = logging.getLogger("django")

from siege_utilities.files.paths import ensure_path_exists


class Command(BaseCommand):
    args = ""
    help = "Takes no arguments, ensures the existence of directories as specified in settings"

    def add_arguments(self, parser):
        parser.add_argument("models", nargs="*")

    def handle(self, *args, **kwargs):

        # get command line specified options
        directories_set = []
        known_directories = list(settings.NECESSARY_PATHS)

        # container variables
        directories_to_work_on = []
        directories_that_cannot_be_worked_on = []
        successes = []
        failures = []

        directories_to_work_on = known_directories

        # start work
        try:
            for d in directories_to_work_on:
                create_the_path(d)
                successes.append(d)
        except Exception as e:
            message = "\n"
            message += f"There was an error at the management command level working on {d}: {e}"
            logger.error(message)
            failures.append(d)

        # count failures
        if len(failures) > 0:
            message = "\n FAILURE"
            message += f"\n The following paths succeeded : {successes}"
            message += f"\n The following paths failed : {failures}"

            logger.error(message)

        else:
            message = "\n SUCCESS"
            message += f"\n The following paths succeeded : {successes}"
            message += f"\n The following paths failed : {failures}"

            logger.info(message)


def create_the_path(desired_path: pathlib.Path) -> bool:

    try:
        ensure_path_exists(desired_path=desired_path)
        return True
    except Exception as e:
        message = "\n"
        message += f"There was an error at the management command level working on {desired_path}: {e}"
        return False
