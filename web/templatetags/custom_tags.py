from django import template

register = template.Library()


@register.filter
def get_range(value):
    return range(value)


@register.filter
def multiply(value, arg):
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0
