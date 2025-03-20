from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)


@register.filter(name="percent_complete")
def percent_complete(value, arg):
    try:
        return int(value / arg * 100)
    except (TypeError, ZeroDivisionError):
        return ""
