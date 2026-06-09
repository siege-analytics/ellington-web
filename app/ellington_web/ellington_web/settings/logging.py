# python imports

import os
from pathlib import Path

#  django imports

from django.conf import settings

# log file

log_file_name = "django_application.log"
Path(settings.LOGS_DIRECTORY).mkdir(parents=True, exist_ok=True)
LOG_PATH = str(settings.LOGS_DIRECTORY / log_file_name)

# doing something very stupid here
try:
    Path(LOG_PATH).touch(exist_ok=True)  # will create file, if it exists will do nothing
except Exception as e:
    message ="\n"
    message +=f"Pathlib method to create the logging file didn't work, trying OS lib method:{e}"
    logging.error(message)
try:
    if not os.path.exists(LOG_PATH):
        f = open(LOG_PATH, 'w+').close()
except Exception as e:
    message ="\n"
    message +=f"OS method to create the logging file didn't work, Alfred E. Neumann:{e}"
    logging.error(message)


# Create a LOGGING dictionary
LOGGING = {
    # Use v1 of the logging config schema
    'version': 1,
    # Continue to use existing loggers
    'disable_existing_loggers': False,
    # Add a verbose formatter
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {funcName} {filename:s} {lineno:d} {message}',
            'style': '{',
        },
    },
    # Create a log handler that prints logs to the terminal
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            # Add the verbose formatter
            'formatter': 'verbose',
        },
        # Add a handler to write logs to a file
        'file': {
            # Use the FileHandler class
            'class': 'logging.FileHandler',
            # Specify a local log file as a raw string. Use your app's directory.
            'filename': LOG_PATH,
            'formatter': 'verbose',
        },
    },
    # Define the root logger's settings
    'root': {
        # Use the console and file logger
        'handlers': ['console', 'file'],
        'level': 'DEBUG',
    },
    # Define the django log module's settings
    'loggers': {
        'django': {
            # Use the console and file logger
            'handlers': ['console', 'file'],
            'level': os.getenv('DJANGO_LOG_LEVEL', 'INFO'),
            'propagate': False,
        },
    },
}