# Generated by Django 5.1.2 on 2025-01-05 04:30

import django_project.storage_backends
import pages.models
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("pages", "0014_alter_book_image"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="author",
            options={"ordering": ["last_name", "first_name"]},
        ),
        migrations.AlterModelOptions(
            name="book",
            options={"ordering": ["title"]},
        ),
        migrations.AlterModelOptions(
            name="category",
            options={"ordering": ["name"]},
        ),
        migrations.AlterModelOptions(
            name="userfavoritelibrary",
            options={"ordering": ["library__name"]},
        ),
        migrations.AlterModelOptions(
            name="webplatform",
            options={"ordering": ["name"]},
        ),
        migrations.AlterField(
            model_name="book",
            name="image",
            field=models.ImageField(
                blank=True,
                null=True,
                storage=django_project.storage_backends.MediaStorage(),
                upload_to=pages.models.upload_to_book_images,
            ),
        ),
        migrations.AlterUniqueTogether(
            name="author",
            unique_together={("first_name", "last_name")},
        ),
    ]