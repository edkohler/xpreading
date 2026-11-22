from django.conf import settings
from django.db import migrations


def set_site(apps, schema_editor):
    """Name the default Site so allauth emails say "XP Reading", not example.com."""
    Site = apps.get_model("sites", "Site")
    domain = getattr(settings, "SITEMAP_DOMAIN", "xpreading.com")
    Site.objects.update_or_create(
        id=getattr(settings, "SITE_ID", 1),
        defaults={"domain": domain, "name": "XP Reading"},
    )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        ("sites", "0002_alter_domain_unique"),
    ]

    operations = [migrations.RunPython(set_site, migrations.RunPython.noop)]
