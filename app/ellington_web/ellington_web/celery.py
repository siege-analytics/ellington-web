"""
Celery configuration for ellington_web project
"""

import os
from celery import Celery

# Set the default Django settings module  
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ellington_web.settings')

app = Celery('ellington_web')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related config keys
#   should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django apps.
# All GADM tasks (SedonaDB, pipelined, optimized) are consolidated in locations/tasks.py
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')

