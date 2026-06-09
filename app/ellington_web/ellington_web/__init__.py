# This will make sure the app is always imported when
# Django starts so that shared_task will use this app.
from . import celery as celery_module
from .celery import app as celery_app

# Export both celery (module) and celery_app for different access patterns
__all__ = ('celery_app', 'celery_module')

# Make celery accessible as ellington_web.celery (for celery -A ellington_web)
celery = celery_module
