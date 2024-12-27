from storages.backends.s3boto3 import S3Boto3Storage

class MediaStorage(S3Boto3Storage):
    location = "media"  # Ensure media files are stored under /media/
    file_overwrite = False  # Prevent overwriting files with the same name
