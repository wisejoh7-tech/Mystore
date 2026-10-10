from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path("", views.base, name="home"),
    path("register/", views.register, name="register"),
    path("verify/", views.verify_code, name="verify_code"),
    path("login/", views.login_view, name="login"),
    path("login-phone/", views.login_with_phone, name="login_with_phone"),
    path("verify-phone/", views.verify_phone_login, name="verify_phone_login"),
    path("logout/", views.logout_view, name="logout"),
    path("admin-login/", views.admin_login, name="admin_login"),
    path("admin-register/", views.admin_register, name="admin_register"),

    # Password Reset URLs
    path("password-reset/", auth_views.PasswordResetView.as_view(), name="password_reset"),
    path("password-reset/done/", auth_views.PasswordResetDoneView.as_view(), name="password_reset_done"),
    path("password-reset-confirm/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("password-reset-complete/", auth_views.PasswordResetCompleteView.as_view(), name="password_reset_complete"),

    # Listings
    path("men/", views.men, name="men"),
    path("women/", views.women, name="women"),
    path("wrist/", views.wrist, name="wristcollection"),
    path("collection/", views.collection, name="collection"),
    path("categories/", views.all_categories, name="all_categories"),
    path("category/<slug:category_name>/", views.category_view, name="category_view"),
    path("search/", views.search, name="search"),
    path("live-search/", views.live_search, name="live_search"),
    path("subscribe-newsletter/", views.subscribe_newsletter, name="subscribe_newsletter"),

    # Product Detail
    path("product/<str:prod_type>/<int:pk>/", views.product_detail, name="product_detail"),

    # Cart
    path("cart/", views.cart_view, name="cart"),
    path("cart/add/", views.add_to_cart, name="add_to_cart"),
    path("cart/remove/", views.remove_from_cart, name="remove_from_cart"),
    path("cart/sync/", views.sync_cart, name="sync_cart"),
    path("cart/data/", views.get_cart_data, name="get_cart_data"),

    # Checkout & Orders
    path("pay/", views.pay, name="pay"),
    path("submit_order/", views.submit_order, name="submit_order"),

    # Dashboard & Account
    path("dashboard/", views.dashboard, name="dashboard"),
    path("dashboard/settings/update/", views.update_dashboard_settings, name="update_dashboard_settings"),
    path("wishlist/toggle/", views.toggle_wishlist, name="toggle_wishlist"),
    path("review/add/", views.add_review, name="add_review"),

    # Help & Info
    path("help/", views.help_center, name="help_center"),
    path("contact/", views.contact, name="contact"),
    path("track-order/", views.track_order, name="track_order"),
    path("order-cancellation/", views.order_cancellation, name="order_cancellation"),
    path("returns-refunds/", views.returns_refunds, name="returns_refunds"),
    path("terms-privacy/", views.terms_privacy, name="terms_privacy"),
    path("about-us/", views.about_us, name="about_us"),
    path("careers/", views.careers, name="careers"),
    path("express-delivery/", views.express_delivery, name="express_delivery"),
    path("privacy-notice/", views.privacy_notice, name="privacy_notice"),
    path("sell-on-mystore/", views.sell, name="sell"),
    path("sales-consultant/", views.sales_consultant, name="sales_consultant"),
    path("logistics-partner/", views.logistics_partner, name="logistics_partner"),
    path("orders/", views.orders_view, name="orders"),
    path("orders/clear/", views.clear_order_history, name="clear_order_history"),
    path("orders/mark-paid/<int:order_id>/", views.mark_order_paid, name="mark_order_paid"),
    path("orders/invoice/<int:order_id>/", views.download_invoice, name="download_invoice"),
    path("payment/initiate/<int:order_id>/", views.initiate_payment, name="initiate_payment"),
    path("payment/verify/", views.verify_payment, name="verify_payment"),
    path("admin-dashboard/", views.admin_dashboard, name="admin_dashboard"),
    path("admin-register-home/", views.admin_register_home, name="admin_register_home"),
    path(".well-known/appspecific/<str:name>.json", views.handle_chrome_devtools, name="chrome_devtools"),
]
