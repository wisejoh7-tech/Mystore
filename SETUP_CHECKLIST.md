# 🚀 MyStore Final Setup Checklist

This document contains the final steps to get your professional e-commerce platform running in a production or development environment.

## 1. Environment Configuration (`.env`)
Create or update your `.env` file in the root directory with the following variables:

```env
# Security & Debug
SECRET_KEY=your-secret-key-here
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1,web

# Database (PostgreSQL)
DATABASE_URL=postgres://postgres:postgres@db:5432/postgres

# Redis & Real-time (Channels)
REDIS_URL=redis://redis:6379/0

# Google OAuth Configuration
GOOGLE_CLIENT_ID=your_google_client_id_here
GOOGLE_CLIENT_SECRET=your_google_client_secret_here

# Paystack API Keys
PAYSTACK_PUBLIC_KEY=pk_test_your_public_key
PAYSTACK_SECRET_KEY=sk_test_your_secret_key

# Cloudinary (Image Hosting)
CLOUDINARY_CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_api_key
CLOUDINARY_API_SECRET=your_api_secret

# Email (Resend or Gmail SMTP)
RESEND_API_KEY=re_your_resend_api_key
EMAIL_HOST=smtp.resend.com
EMAIL_PORT=465
EMAIL_USE_SSL=True
EMAIL_HOST_USER=resend
EMAIL_HOST_PASSWORD=re_your_resend_api_key
DEFAULT_FROM_EMAIL=onboarding@resend.dev
ADMIN_EMAIL=your-admin-email@gmail.com
```

## 2. Launching the Application
Since the project is containerized, use Docker to start all services (Postgres, Redis, Web, Nginx):

```bash
# Build and start services in the background
docker-compose up --build -d
```

## 3. Database & Static Files
Once the containers are running, you must initialize the database and prepare the CSS/JS files:

```bash
# Run migrations to create PostgreSQL tables
docker-compose exec web python manage.py migrate

# Collect all static files for Nginx to serve
docker-compose exec web python manage.py collectstatic --noinput
```

## 4. Create Admin Account
To access the `/admin/` and `/admin-dashboard/` areas:

```bash
docker-compose exec web python manage.py createsuperuser
```

## 5. Key Features Implemented
- **Payment**: Paystack Inline Popup with automated status verification.
- **Invoices**: Branded HTML receipts (email) and PDF downloads.
- **Search**: AJAX-powered Live Search dropdown.
- **Dashboard**: Real-time sales charts and low-stock alerts.
- **Mobile**: Slide-in navigation drawer and horizontal scroll grids.
- **Reliability**: Cloudinary image hosting and Redis-backed cache.

## 6. Production Notes
- Set `DEBUG=False` in your `.env`.
- Ensure your `ALLOWED_HOSTS` includes your actual domain.
- Configure your Paystack Webhook URL to: `https://yourdomain.com/payment/verify/`.
- Ensure SSL (HTTPS) is active on your server for secure payments.
