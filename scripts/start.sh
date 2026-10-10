#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

echo "--- Starting Production Startup Script ---"

# 1. Run Migrations
echo "Running Migrations..."
python manage.py migrate --noinput

# 2. Collect Static Files
echo "Collecting Static Files..."
python manage.py collectstatic --noinput

# 3. Start Gunicorn
echo "Starting Gunicorn with Uvicorn Workers on port ${PORT:-8000}..."
# Use gunicorn for production as it's more robust than running uvicorn directly
# -k uvicorn.workers.UvicornWorker allows it to handle ASGI (Channels)
exec gunicorn drop.asgi:application \
    --bind 0.0.0.0:${PORT:-8000} \
    --workers 4 \
    --worker-class uvicorn.workers.UvicornWorker \
    --access-logformat '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"' \
    --access-logfile -
