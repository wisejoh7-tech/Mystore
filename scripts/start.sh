#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

echo "--- Starting Production Startup Script ---"

# 1. Run Migrations
echo "Fixing Migration History if needed..."
python manage.py fix_migration_history

echo "Running Migrations..."
python manage.py migrate --noinput

# 2. Collect Static Files
echo "Collecting Static Files..."
python manage.py collectstatic --noinput

# 3. Auto-Create/Ensure Superuser (if ADMIN_USERNAME and ADMIN_PASSWORD env vars are set)
if [ -n "$ADMIN_USERNAME" ] && [ -n "$ADMIN_PASSWORD" ]; then
    echo "Auto-creating/updating admin account '$ADMIN_USERNAME'..."
    if [ -n "$ADMIN_EMAIL" ]; then
        python manage.py reset_admin_password --username "$ADMIN_USERNAME" --password "$ADMIN_PASSWORD" --email "$ADMIN_EMAIL"
    else
        python manage.py reset_admin_password --username "$ADMIN_USERNAME" --password "$ADMIN_PASSWORD"
    fi
fi

# 4. Start Gunicorn
echo "Starting Gunicorn with Uvicorn Workers on port ${PORT:-8000}..."
# Use gunicorn for production as it's more robust than running uvicorn directly
# -k uvicorn.workers.UvicornWorker allows it to handle ASGI (Channels)
exec gunicorn drop.asgi:application \
    --bind 0.0.0.0:${PORT:-8000} \
    --workers 4 \
    --worker-class uvicorn.workers.UvicornWorker \
    --access-logformat '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"' \
    --access-logfile -
