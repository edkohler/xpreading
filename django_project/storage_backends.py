import logging

from django.conf import settings
from storages.backends.s3boto3 import S3Boto3Storage

logger = logging.getLogger(__name__)

class StaticStorage(S3Boto3Storage):
    location = 'static'
    default_acl = 'public-read'

class MediaStorage(S3Boto3Storage):
    location = 'media'
    default_acl = 'public-read'
    file_overwrite = False

    def _save(self, name, content):
        try:
            logger.info(f"Attempting to save file: {name}")
            result = super()._save(name, content)
            logger.info(f"File save result: {result}")
            return result
        except Exception as e:
            logger.error(f"Error saving file {name}: {str(e)}")
            raise
