from .models import Cart


def cart_context(request):
    cart_count = 0
    cart_total = 0
    if request.user.is_authenticated:
        cart, _ = Cart.objects.get_or_create(user=request.user)
        cart_count = cart.items.count()
        cart_total = cart.total_price
    else:
        # For guest users, we still rely on JS/Session logic
        pass

    return {
        'cart_count': cart_count,
        'cart_total': cart_total,
    }
