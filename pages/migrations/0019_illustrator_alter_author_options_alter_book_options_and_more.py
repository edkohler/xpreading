# Generated by Django 5.1.2 on 2025-01-20 14:25

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("pages", "0018_category_new_books_release_day_of_year"),
    ]

    operations = [
        migrations.CreateModel(
            name="Illustrator",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("first_name", models.CharField(max_length=100)),
                ("last_name", models.CharField(max_length=100)),
            ],
        ),
        migrations.AlterModelOptions(
            name="author",
            options={},
        ),
        migrations.AlterModelOptions(
            name="book",
            options={},
        ),
        migrations.AddField(
            model_name="book",
            name="illustrator",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="pages.illustrator",
            ),
        ),
    ]
