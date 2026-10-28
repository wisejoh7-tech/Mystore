import random
import logging
import json
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from django.db.models import Q, Avg, Sum, F
from django.http import JsonResponse, HttpResponse
from django.template.loader import get_template
from django.views.decorators.csrf import csrf_exempt
from django.core.paginator import Paginator
from datetime import timedelta
from xhtml2pdf import pisa
import io
from .models import User, OTP, shoe, watch, Category, Cart, CartItem, Order, Wishlist, Review, Expense, ContactMessage, Product
from .forms import RegistrationForm, LoginForm, PhoneLoginForm, ProfileUpdateForm, ContactForm
from .tasks import send_otp_email, send_registration_email, send_sms_otp, send_contact_email
from .services import CartService, InventoryService, OrderService, PaymentService

logger = logging.getLogger(__name__)


def generate_otp():
    return str(random.randint(100000, 999999))


def base(request):
    categories = Category.objects.all()
    featured_shoes = shoe.objects.select_related('category').all()[:8]
    featured_watches = watch.objects.select_related('category').all()[:8]
    flash_shoes = shoe.objects.select_related('category').filter(discount_price__isnull=False)[:8]
    top_watches = watch.objects.select_related('category').all()[:8]
    men_shoes = shoe.objects.select_related('category').filter(target_audience='Male')[:8]
    women_shoes = shoe.objects.select_related('category').filter(target_audience='Female')[:8]

    # New Categories
    appliances = Product.objects.select_related('category').filter(category__name='Home Appliances')[:8]
    accessories = Product.objects.select_related('category').filter(category__name='Computer Accessories')[:8]
    phones = Product.objects.select_related('category').filter(category__name='Phones')[:8]

    # Fetch Recently Viewed Items
    recently_viewed_ids = request.session.get('recently_viewed', [])
    recently_viewed_items = []
    for item_id in recently_viewed_ids:
        try:
            ptype, pk = item_id.split('_')
            if ptype == 'shoe':
                recently_viewed_items.append({'type': 'shoe', 'item': shoe.objects.select_related('category').get(pk=pk)})
            elif ptype == 'watch':
                recently_viewed_items.append({'type': 'watch', 'item': watch.objects.select_related('category').get(pk=pk)})
            else:
                recently_viewed_items.append({'type': 'product', 'item': Product.objects.select_related('category').get(pk=pk)})
        except Exception:
            continue

    context = {
        'categories': categories,
        'featured_shoes': featured_shoes,
        'featured_watches': featured_watches,
        'flash_shoes': flash_shoes,
        'top_watches': top_watches,
        'men_shoes': men_shoes,
        'women_shoes': women_shoes,
        'appliances': appliances,
        'accessories': accessories,
        'phones': phones,
        'recently_viewed': recently_viewed_items,
        'free_shipping_threshold': 50000,
        'flash_sale_end': (timezone.now() + timedelta(days=2)).isoformat(),
    }

    if request.user.is_authenticated and request.user.is_staff:
        shoe_val = shoe.objects.aggregate(total=Sum(F('price') * F('stock')))['total'] or 0
        watch_val = watch.objects.aggregate(total=Sum(F('price') * F('stock')))['total'] or 0
        context['admin_total_goods_value'] = shoe_val + watch_val
        context['admin_total_revenue'] = Order.objects.filter(complete=True).exclude(status='Cancelled').aggregate(revenue=Sum('total'))['revenue'] or 0
        total_exp = Expense.objects.aggregate(expenses=Sum('amount'))['expenses'] or 0
        context['admin_total_expenses'] = total_exp
        context['admin_net_finance'] = context['admin_total_revenue'] - total_exp
        shoe_units = shoe.objects.aggregate(total=Sum('stock'))['total'] or 0
        watch_units = watch.objects.aggregate(total=Sum('stock'))['total'] or 0
        context['admin_total_units'] = shoe_units + watch_units
        context['admin_reg_form'] = RegistrationForm()

    return render(request, 'base_home.html', context)


def register(request):
    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data["password"])
            user.is_active = False
            user.save()

            code = generate_otp()
            OTP.objects.update_or_create(user=user, defaults={'code': code, 'created_at': timezone.now()})

            send_otp_email.delay(user.email, code)
            if user.phone:
                send_sms_otp.delay(user.phone, code)

            request.session['unverified_user_id'] = user.id
            messages.success(request, f"A verification code has been sent to {user.email} and {user.phone if user.phone else ''}. Please enter it to complete your registration.")
            return redirect("verify_code")
    else:
        form = RegistrationForm()
    return render(request, "register.html", {"form": form})


@login_required
def admin_register_home(request):
    if not request.user.is_staff:
        raise PermissionDenied
    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data["password"])
            user.is_staff = True
            user.is_active = True
            user.save()
            messages.success(request, f"Admin account '{user.username}' created successfully!")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    return redirect("home")


def verify_code(request):
    user_id = request.session.get('unverified_user_id')
    if not user_id:
        return redirect("register")

    if request.method == "POST":
        code = request.POST.get("code")
        try:
            user = User.objects.get(id=user_id)
            otp = OTP.objects.get(user=user, code=code)

            if (timezone.now() - otp.created_at).total_seconds() > 300:
                messages.error(request, "Code expired. Please register again.")
                return redirect("register")

            user.is_active = True
            user.save()
            otp.delete()

            login(request, user)
            send_registration_email.delay(user.email, user.username)
            del request.session['unverified_user_id']
            messages.success(request, "Account verified and registered successfully!")
            return redirect("home")
        except (User.DoesNotExist, OTP.DoesNotExist):
            messages.error(request, "Invalid code.")

    return render(request, "verify.html")


def login_view(request):
    try:
        if request.method == "POST":
            form = LoginForm(data=request.POST)
            if form.is_valid():
                user = form.get_user()
                login(request, user)
                return redirect("home")
            else:
                logger.warning(f"Login failed for form: {form.errors}")
        else:
            form = LoginForm()
        return render(request, "login.html", {"form": form})
    except Exception as e:
        logger.error(f"Error in login_view: {e}", exc_info=True)
        raise e


def login_with_phone(request):
    if request.method == "POST":
        form = PhoneLoginForm(request.POST)
        if form.is_valid():
            phone = form.cleaned_data["phone"]
            try:
                user = User.objects.get(phone=phone)
                code = generate_otp()
                OTP.objects.update_or_create(user=user, defaults={'code': code, 'created_at': timezone.now()})

                if user.email:
                    send_otp_email.delay(user.email, code)
                    messages.success(request, "A login code has been sent to your registered email.")

                if user.phone:
                    send_sms_otp.delay(user.phone, code)
                    messages.success(request, f"A login code has been sent to your phone number: {user.phone}")

                request.session['phone_login_user_id'] = user.id
                return redirect("verify_phone_login")
            except User.DoesNotExist:
                messages.error(request, "No account found with this phone number.")
    else:
        form = PhoneLoginForm()
    return render(request, "login_phone.html", {"form": form})


def verify_phone_login(request):
    user_id = request.session.get('phone_login_user_id')
    if not user_id:
        return redirect("login_with_phone")

    if request.method == "POST":
        code = request.POST.get("code")
        try:
            user = User.objects.get(id=user_id)
            otp = OTP.objects.get(user=user, code=code)
            user.is_active = True
            user.save()
            otp.delete()
            login(request, user)
            del request.session['phone_login_user_id']
            return redirect("home")
        except User.DoesNotExist:
            messages.error(request, "User session expired. Please log in again.")
            return redirect("login_with_phone")
        except OTP.DoesNotExist:
            messages.error(request, "Invalid or expired code. Please try again.")
    return render(request, "verify_phone.html")


def logout_view(request):
    logout(request)
    return redirect("home")


def admin_login(request):
    if request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser):
        return redirect("admin_dashboard")

    if request.method == "POST":
        form = LoginForm(data=request.POST)
        if form.is_valid():
            user = form.get_user()
            if user.is_staff or user.is_superuser:
                if not user.is_staff:
                    user.is_staff = True
                if not user.is_active:
                    user.is_active = True
                user.save()
                login(request, user)
                messages.success(request, f"Welcome back, {user.username}!")
                return redirect("admin_dashboard")
            else:
                messages.error(request, "Admin access only. Please use regular login.")
    else:
        form = LoginForm()

    return render(request, "admin_login.html", {"form": form})


def admin_register(request):
    if not request.user.is_authenticated or not request.user.is_staff:
        messages.error(request, "Admin registration requires staff approval. Contact an administrator.")
        return redirect("home")

    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data["password"])
            user.is_staff = True
            user.is_active = True
            user.save()
            messages.success(request, f"Admin account '{user.username}' created successfully!")
            return redirect("admin_dashboard")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    else:
        form = RegistrationForm()

    return render(request, "admin_register.html", {"form": form})


def men(request):
    category_filter = request.GET.get('category', '')
    query = request.GET.get('q', '')
    min_price = request.GET.get('min_price', '')
    max_price = request.GET.get('max_price', '')
    brand_filter = request.GET.get('brand', '')

    shoes = shoe.objects.select_related('category').filter(target_audience='Male')

    if category_filter:
        shoes = shoes.filter(category__name=category_filter)
    if query:
        shoes = shoes.filter(Q(name__icontains=query) | Q(brand__icontains=query))
    if min_price:
        shoes = shoes.filter(price__gte=min_price)
    if max_price:
        shoes = shoes.filter(price__lte=max_price)
    if brand_filter:
        shoes = shoes.filter(brand=brand_filter)

    brands = shoe.objects.filter(target_audience='Male').values_list('brand', flat=True).distinct()
    categories = Category.objects.filter(shoes__target_audience='Male').distinct()

    paginator = Paginator(shoes, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'shoes': page_obj,
        'page_obj': page_obj,
        'brands': brands,
        'categories': categories,
        'selected_category': category_filter,
        'selected_brand': brand_filter,
        'min_price': min_price,
        'max_price': max_price,
    }
    return render(request, 'men.html', context)


def women(request):
    category_filter = request.GET.get('category', '')
    query = request.GET.get('q', '')
    min_price = request.GET.get('min_price', '')
    max_price = request.GET.get('max_price', '')
    brand_filter = request.GET.get('brand', '')

    shoes = shoe.objects.select_related('category').filter(target_audience='Female')

    if category_filter:
        shoes = shoes.filter(category__name=category_filter)
    if query:
        shoes = shoes.filter(Q(name__icontains=query) | Q(brand__icontains=query))
    if min_price:
        shoes = shoes.filter(price__gte=min_price)
    if max_price:
        shoes = shoes.filter(price__lte=max_price)
    if brand_filter:
        shoes = shoes.filter(brand=brand_filter)

    brands = shoe.objects.filter(target_audience='Female').values_list('brand', flat=True).distinct()
    categories = Category.objects.filter(shoes__target_audience='Female').distinct()

    paginator = Paginator(shoes, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'shoes': page_obj,
        'page_obj': page_obj,
        'brands': brands,
        'categories': categories,
        'selected_category': category_filter,
        'selected_brand': brand_filter,
        'min_price': min_price,
        'max_price': max_price,
    }
    return render(request, 'women.html', context)


def wrist(request):
    watches = watch.objects.select_related('category').all()
    paginator = Paginator(watches, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(request, 'wristcollection.html', {'watches': page_obj, 'page_obj': page_obj})


def category_view(request, category_name):
    clean_name = category_name.replace('-', ' ').title()
    products = Product.objects.select_related('category').filter(category__name__iexact=clean_name)
    shoes = shoe.objects.select_related('category').filter(category__name__iexact=clean_name)
    watches = watch.objects.select_related('category').filter(category__name__iexact=clean_name)

    return render(request, 'category_detail.html', {
        'category_name': clean_name,
        'products': products,
        'shoes': shoes,
        'watches': watches
    })


@login_required
def orders_view(request):
    orders = Order.objects.filter(user=request.user).select_related('user').order_by('-created_at') if request.user.is_authenticated else []
    clear_cart = request.session.pop('clear_local_cart', False)
    return render(request, 'order.html', {
        'orders': orders,
        'clear_cart': clear_cart
    })


def collection(request):
    shoes = shoe.objects.select_related('category').filter(target_audience='Collections')
    paginator = Paginator(shoes, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(request, 'collection.html', {'shoes': page_obj, 'page_obj': page_obj})


def all_categories(request):
    categories = Category.objects.all()
    return render(request, 'all_categories.html', {'categories': categories})


def product_detail(request, prod_type, pk):
    if prod_type == 'shoe':
        product = get_object_or_404(shoe.objects.select_related('category'), pk=pk)
    elif prod_type == 'watch':
        product = get_object_or_404(watch.objects.select_related('category'), pk=pk)
    else:
        product = get_object_or_404(Product.objects.select_related('category'), pk=pk)

    recently_viewed = request.session.get('recently_viewed', [])
    item_id = f"{prod_type}_{pk}"
    if item_id in recently_viewed:
        recently_viewed.remove(item_id)
    recently_viewed.insert(0, item_id)
    request.session['recently_viewed'] = recently_viewed[:6]

    reviews = product.reviews.select_related('user').all().order_by('-created_at')
    average_rating = reviews.aggregate(Avg('rating'))['rating__avg'] or 0

    if prod_type == 'shoe':
        related_products = shoe.objects.select_related('category').filter(category=product.category).exclude(pk=product.pk)[:4]
    else:
        related_products = watch.objects.select_related('category').filter(category=product.category).exclude(pk=product.pk)[:4]

    in_wishlist = False
    if request.user.is_authenticated:
        wishlist, _ = Wishlist.objects.get_or_create(user=request.user)
        if prod_type == 'shoe':
            in_wishlist = wishlist.shoes.filter(id=product.id).exists()
        else:
            in_wishlist = wishlist.watches.filter(id=product.id).exists()

    context = {
        'product': product,
        'prod_type': prod_type,
        'reviews': reviews,
        'average_rating': average_rating,
        'stars_range': range(1, 6),
        'related_products': related_products,
        'low_stock_threshold': 5,
        'in_wishlist': in_wishlist,
    }
    return render(request, 'product_detail.html', context)


def search(request):
    query = request.GET.get('q', '')
    category_name = request.GET.get('category', '')

    shoes = shoe.objects.select_related('category').all()
    watches = watch.objects.select_related('category').all()

    if query:
        shoes = shoes.filter(Q(name__icontains=query) | Q(brand__icontains=query))
        watches = watches.filter(Q(name__icontains=query) | Q(brand__icontains=query))

    if category_name:
        shoes = shoes.filter(category__name__icontains=category_name)
        watches = watches.filter(category__name__icontains=category_name)

    return render(request, 'search_results.html', {
        'shoes': shoes,
        'watches': watches,
        'query': query,
        'category_name': category_name
    })


def live_search(request):
    query = request.GET.get('q', '')
    if len(query) < 2:
        return JsonResponse({'results': []})

    shoes = shoe.objects.filter(Q(name__icontains=query) | Q(brand__icontains=query))[:5]
    watches = watch.objects.filter(Q(name__icontains=query) | Q(brand__icontains=query))[:5]

    results = []
    for s in shoes:
        results.append({
            'name': f"{s.brand or ''} {s.name}".strip(),
            'price': float(s.discount_price or s.price),
            'url': f"/product/shoe/{s.id}/",
            'image': s.image.url if s.image else '',
            'category': 'Shoe'
        })
    for w in watches:
        results.append({
            'name': f"{w.brand or ''} {w.name}".strip(),
            'price': float(w.discount_price or w.price),
            'url': f"/product/watch/{w.id}/",
            'image': w.image.url if w.image else '',
            'category': 'Watch'
        })

    return JsonResponse({'results': results})


@login_required
def dashboard(request):
    orders = Order.objects.filter(user=request.user).select_related('user')
    wishlist, _ = Wishlist.objects.get_or_create(user=request.user)
    profile_form = ProfileUpdateForm(instance=request.user)
    return render(request, 'dashboard.html', {
        'orders': orders,
        'wishlist': wishlist,
        'profile_form': profile_form,
    })


@login_required
def update_dashboard_settings(request):
    if request.method != 'POST':
        return redirect('dashboard')

    form = ProfileUpdateForm(request.POST, instance=request.user)
    if form.is_valid():
        user = form.save(commit=False)
        new_password = form.cleaned_data.get('new_password')
        if new_password:
            user.set_password(new_password)
        user.save()
        if new_password:
            update_session_auth_hash(request, user)
        messages.success(request, 'Your account settings have been updated.')
        return redirect('dashboard')

    orders = Order.objects.filter(user=request.user).select_related('user')
    wishlist, _ = Wishlist.objects.get_or_create(user=request.user)
    return render(request, 'dashboard.html', {
        'orders': orders,
        'wishlist': wishlist,
        'profile_form': form,
    })


def cart_view(request):
    session_key = request.session.session_key or ""
    cart = CartService.get_or_create_cart(request.user, session_key)
    upsell_products = []
    if not cart or cart.items.count() == 0:
        upsell_products = list(shoe.objects.select_related('category').all()[:4])

    return render(request, 'cart.html', {
        'cart': cart,
        'upsell_products': upsell_products
    })


def add_to_cart(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            prod_type = data.get('type')
            prod_id = data.get('id')
            quantity = int(data.get('quantity', 1))

            if not request.session.session_key:
                request.session.create()

            cart = CartService.get_or_create_cart(request.user, request.session.session_key)
            CartService.add_to_cart(cart, prod_type, prod_id, quantity)

            return JsonResponse({'status': 'success', 'cart_count': cart.items.count()})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})
    return JsonResponse({'status': 'error'}, status=400)


def remove_from_cart(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            item_id = data.get('item_id')
            session_key = request.session.session_key or ""
            cart = CartService.get_or_create_cart(request.user, session_key)
            CartService.remove_from_cart(cart, item_id)
            cart_count = cart.items.count() if cart else 0
            return JsonResponse({'status': 'success', 'cart_count': cart_count})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})
    return JsonResponse({'status': 'error'}, status=400)


@login_required
def sync_cart(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            local_cart = data.get('cart', [])
            db_cart = CartService.sync_cart(request.user, local_cart)
            return JsonResponse({'status': 'success', 'cart_count': db_cart.items.count()})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})
    return JsonResponse({'status': 'error'}, status=400)


def get_cart_data(request):
    session_key = request.session.session_key or ""
    cart = CartService.get_or_create_cart(request.user, session_key)
    items = CartService.get_cart_data(cart)
    return JsonResponse({'status': 'ok', 'cart': items})


@login_required
def pay(request):
    return render(request, 'pay.html', {
        'PAYSTACK_PUBLIC_KEY': settings.PAYSTACK_PUBLIC_KEY
    })


@login_required
def submit_order(request):
    if request.method == "POST":
        address = request.POST.get('delivery_address')
        phone = request.POST.get('phone')
        confirmed_acc = request.POST.get('confirmed_account_number')
        payment_method = request.POST.get('payment_method', 'Bank Transfer')
        cart_json = request.POST.get('cart_json')

        try:
            order = OrderService.create_order(
                user=request.user,
                cart_json=cart_json,
                delivery_address=address,
                phone=phone,
                payment_method=payment_method,
                confirmed_acc=confirmed_acc
            )

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'status': 'success',
                    'order_id': order.id,
                    'total': float(order.total),
                    'payment_method': payment_method,
                    'clear_cart': True
                })

            if payment_method == 'Card Payment':
                return redirect('initiate_payment', order_id=order.id)

            messages.success(request, f"Order #{order.id} submitted successfully! Your cart has been cleared.")
            request.session['clear_local_cart'] = True
            return redirect('orders')

        except ValueError as e:
            messages.error(request, str(e))
            return redirect('cart')
        except Exception as e:
            messages.error(request, f"Error processing order: {str(e)}")
            return redirect('cart')

    return redirect('cart')


@login_required
def toggle_wishlist(request):
    if request.method == "POST":
        prod_type = request.POST.get('type')
        prod_id = request.POST.get('id')
        wishlist, _ = Wishlist.objects.get_or_create(user=request.user)

        added = False
        if prod_type == 'shoe':
            product = get_object_or_404(shoe, id=prod_id)
            if product in wishlist.shoes.all():
                wishlist.shoes.remove(product)
            else:
                wishlist.shoes.add(product)
                added = True
        elif prod_type == 'watch':
            product = get_object_or_404(watch, id=prod_id)
            if product in wishlist.watches.all():
                wishlist.watches.remove(product)
            else:
                wishlist.watches.add(product)
                added = True

        return JsonResponse({'status': 'success', 'added': added})
    return JsonResponse({'status': 'error'}, status=400)


@login_required
def add_review(request):
    if request.method == "POST":
        try:
            if request.content_type == 'application/json':
                data = json.loads(request.body)
            else:
                data = request.POST

            prod_type = data.get('type')
            prod_id = data.get('id')
            rating = int(data.get('rating', 5))
            comment = data.get('comment', '')

            if prod_type == 'shoe':
                item = get_object_or_404(shoe, id=prod_id)
                Review.objects.update_or_create(
                    user=request.user,
                    shoe_item=item,
                    defaults={'rating': rating, 'comment': comment}
                )
            elif prod_type == 'watch':
                item = get_object_or_404(watch, id=prod_id)
                Review.objects.update_or_create(
                    user=request.user,
                    watch_item=item,
                    defaults={'rating': rating, 'comment': comment}
                )
            else:
                raise Exception("Invalid product type")

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'application/json':
                return JsonResponse({'status': 'success'})

            messages.success(request, "Review submitted!")
            return redirect('orders')
        except Exception as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'application/json':
                return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
            messages.error(request, f"Error: {str(e)}")
            return redirect('orders')
    return redirect('orders')


def help_center(request):
    return render(request, 'help_center.html')


def contact(request):
    if request.method == "POST":
        form = ContactForm(request.POST)
        if form.is_valid():
            name = form.cleaned_data['name']
            email = form.cleaned_data['email']
            subject = form.cleaned_data['subject']
            message = form.cleaned_data['message']

            ContactMessage.objects.create(name=name, email=email, subject=subject, message=message)
            send_contact_email.delay(name, email, subject, message)

            messages.success(request, "Your message has been sent successfully. We will get back to you soon!")
            return redirect('contact')
    else:
        form = ContactForm()
    return render(request, 'contact.html', {'form': form})


def track_order(request):
    order_id = request.GET.get('order_id')
    contact = request.GET.get('contact')
    order_status = None
    error_msg = None

    if order_id and contact:
        try:
            order = Order.objects.filter(id=order_id.replace('ORD-', '')).filter(
                Q(phone=contact) | Q(user__email=contact)
            ).first()

            if order:
                order_status = order.status
            else:
                error_msg = "Order not found. Please check your Order ID and Contact details."
        except Exception:
            error_msg = "Invalid Order ID format."

    return render(request, 'track_order.html', {
        'order_status': order_status,
        'error_msg': error_msg,
        'searched': bool(order_id)
    })


def order_cancellation(request):
    return render(request, 'order_cancellation.html')


def returns_refunds(request):
    return render(request, 'returns_refunds.html')


def terms_privacy(request):
    return render(request, 'terms_privacy.html')


def about_us(request):
    return render(request, 'about_us.html')


def careers(request):
    return render(request, 'careers.html')


def express_delivery(request):
    return render(request, 'express_delivery.html')


def privacy_notice(request):
    return render(request, 'privacy_notice.html')


def sell(request):
    return render(request, 'sell.html')


def sales_consultant(request):
    return render(request, 'sales_consultant.html')


def logistics_partner(request):
    return render(request, 'logistics_partner.html')


def handle_chrome_devtools(request, name):
    return JsonResponse({}, status=404)


@login_required
def clear_order_history(request):
    if request.method == "POST":
        Order.objects.filter(user=request.user).delete()
        messages.success(request, "Order history cleared.")
    return redirect('orders')


@login_required
def mark_order_paid(request, order_id):
    if request.method == "POST":
        order = get_object_or_404(Order, id=order_id, user=request.user)
        if order.status == "Processing" or order.status == "Pending":
            OrderService.complete_order(order)
            messages.success(request, f"Order #{order_id} marked as paid and completed!")
        else:
            messages.warning(request, "This order cannot be marked as paid.")
    return redirect('orders')


@login_required
def initiate_payment(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    callback_url = request.build_absolute_uri('/payment/verify/')
    res_data = PaymentService.initialize_paystack_transaction(
        user_email=request.user.email,
        amount=order.total,
        callback_url=callback_url,
        order_id=order.id
    )
    if res_data.get("status"):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'status': 'success', 'authorization_url': res_data["data"]["authorization_url"], 'access_code': res_data["data"]["access_code"]})
        return redirect(res_data["data"]["authorization_url"])
    else:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'status': 'error', 'message': res_data.get('message')})
        messages.error(request, "Failed to initialize payment with Paystack.")
        return redirect('orders')


def verify_payment(request):
    reference = request.GET.get('reference')
    if not reference:
        messages.error(request, "Missing transaction reference.")
        return redirect('orders')

    res_data = PaymentService.verify_paystack_transaction(reference)

    if res_data.get("status") and res_data.get("data", {}).get("status") == "success":
        order_id = res_data["data"]["metadata"]["order_id"]
        order = get_object_or_404(Order, id=order_id)
        OrderService.complete_order(order, reference=reference)
        messages.success(request, "Payment successful!")
        return redirect('orders')
    else:
        messages.error(request, "Payment verification failed.")
        return redirect('orders')


@csrf_exempt
def paystack_webhook(request):
    if request.method != "POST":
        return HttpResponse(status=405)

    signature = request.headers.get('X-Paystack-Signature')
    payload = request.body

    if not PaymentService.verify_webhook_signature(payload, signature):
        logger.warning("Invalid Paystack webhook signature")
        return HttpResponse(status=400)

    try:
        event_data = json.loads(payload.decode('utf-8'))
        success, message = PaymentService.process_webhook_event(event_data)
        if success:
            return HttpResponse(status=200)
        return HttpResponse(message, status=400)
    except Exception as exc:
        logger.error(f"Error handling Paystack webhook: {exc}")
        return HttpResponse("Internal Server Error", status=500)


@login_required
def download_invoice(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)

    items = order.items_list
    for item in items:
        item['price'] = float(item.get('price', 0))
        item['total'] = item['price'] * int(item.get('quantity', 1))

    context = {
        'order': order,
        'user': request.user,
        'items': items,
    }

    template = get_template('invoice.html')
    html = template.render(context)

    result = io.BytesIO()
    pdf = pisa.pisaDocument(io.BytesIO(html.encode("UTF-8")), result)

    if not pdf.err:
        response = HttpResponse(result.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="Invoice_{order.id}.pdf"'
        return response

    return HttpResponse("Error generating PDF", status=400)


def subscribe_newsletter(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            email = data.get('email')
            logger.info(f"New newsletter subscription: {email}")
            return JsonResponse({'status': 'success', 'message': 'Thank you for subscribing!'})
        except Exception:
            return JsonResponse({'status': 'error', 'message': 'Invalid request'})
    return JsonResponse({'status': 'error'}, status=400)


@login_required
def admin_dashboard(request):
    if not request.user.is_staff:
        raise PermissionDenied

    shoe_inventory_value = shoe.objects.aggregate(total=Sum(F('price') * F('stock')))['total'] or 0
    watch_inventory_value = watch.objects.aggregate(total=Sum(F('price') * F('stock')))['total'] or 0
    product_inventory_value = Product.objects.aggregate(total=Sum(F('price') * F('stock')))['total'] or 0
    total_inventory_value = shoe_inventory_value + watch_inventory_value + product_inventory_value

    shoe_stock_cost = shoe.objects.aggregate(total=Sum(F('cost_price') * F('stock')))['total'] or 0
    watch_stock_cost = watch.objects.aggregate(total=Sum(F('cost_price') * F('stock')))['total'] or 0
    product_stock_cost = Product.objects.aggregate(total=Sum(F('cost_price') * F('stock')))['total'] or 0
    total_stock_cost_in_inventory = shoe_stock_cost + watch_stock_cost + product_stock_cost

    completed_orders = Order.objects.filter(complete=True).exclude(status='Cancelled').select_related('user')
    total_revenue = completed_orders.aggregate(total=Sum('total'))['total'] or 0
    total_sales_count = completed_orders.count()

    total_items_sold = 0
    for order in completed_orders:
        try:
            order_items = json.loads(order.items_json or '[]')
            for item in order_items:
                total_items_sold += int(item.get('quantity', 1))
        except Exception:
            continue

    out_of_stock_shoes = shoe.objects.filter(stock__lte=0).count()
    out_of_stock_watches = watch.objects.filter(stock__lte=0).count()
    out_of_stock_products = Product.objects.filter(stock__lte=0).count()
    out_of_stock_count = out_of_stock_shoes + out_of_stock_watches + out_of_stock_products

    total_expenses = Expense.objects.aggregate(total=Sum('amount'))['total'] or 0

    shoe_units = shoe.objects.aggregate(total=Sum('stock'))['total'] or 0
    watch_units = watch.objects.aggregate(total=Sum('stock'))['total'] or 0
    product_units = Product.objects.aggregate(total=Sum('stock'))['total'] or 0
    total_units = shoe_units + watch_units + product_units

    net_profit = total_revenue - total_expenses

    low_stock_shoes = shoe.objects.filter(stock__gt=0, stock__lte=5).select_related('category')
    low_stock_watches = watch.objects.filter(stock__gt=0, stock__lte=5).select_related('category')

    last_7_days = [(timezone.now() - timedelta(days=i)).date() for i in range(6, -1, -1)]
    revenue_data = []
    expense_data = []
    labels = [d.strftime("%b %d") for d in last_7_days]

    for day in last_7_days:
        rev = Order.objects.filter(complete=True, created_at__date=day).aggregate(total_rev=Sum('total'))['total_rev'] or 0
        exp = Expense.objects.filter(date__date=day).aggregate(total_exp=Sum('amount'))['total_exp'] or 0
        revenue_data.append(float(rev))
        expense_data.append(float(exp))

    recent_orders = Order.objects.select_related('user').all().order_by('-created_at')[:10]
    recent_expenses = Expense.objects.all().order_by('-date')[:10]

    context = {
        'total_inventory_value': total_inventory_value,
        'total_stock_cost_in_inventory': total_stock_cost_in_inventory,
        'total_revenue': total_revenue,
        'total_expenses': total_expenses,
        'net_profit': net_profit,
        'total_units': total_units,
        'total_sales_count': total_sales_count,
        'total_items_sold': total_items_sold,
        'out_of_stock_count': out_of_stock_count,
        'recent_orders': recent_orders,
        'recent_expenses': recent_expenses,
        'low_stock_shoes': low_stock_shoes,
        'low_stock_watches': low_stock_watches,
        'chart_labels': json.dumps(labels),
        'chart_revenue': json.dumps(revenue_data),
        'chart_expenses': json.dumps(expense_data),
    }
    return render(request, 'admin_dashboard.html', context)
