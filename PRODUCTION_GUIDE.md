# 🚀 Production Deployment & Management Guide

This document contains all the steps required to deploy, manage, and maintain your "Drop Down" store in a real-world environment.

---

## 1. Initial Deployment (Render.com)
Your project is already configured for Render using the `render.yaml` blueprint.

1. **Connect GitHub**: Log in to [Render Dashboard](https://dashboard.render.com), click **New +** > **Blueprint**, and select your `drop-down` repo.
2. **Environment Variables**: Once the service is created, go to the **drop-web** service > **Environment** and add:
   - `GOOGLE_CLIENT_ID`: OAuth 2.0 Web Client ID from Google Cloud Console.
   - `GOOGLE_CLIENT_SECRET`: OAuth 2.0 Web Client Secret from Google Cloud Console.
   - `CLOUDINARY_CLOUD_NAME`: From your Cloudinary dashboard.
   - `CLOUDINARY_API_KEY`: From your Cloudinary dashboard.
   - `CLOUDINARY_API_SECRET`: From your Cloudinary dashboard.
   - `PAYSTACK_SECRET_KEY`: Use your **Live** secret key from Paystack.
   - `SECRET_KEY`: (Render generates one, but you can paste your own).
   - `SENTRY_DSN`: (Optional) From your Sentry.io dashboard.

---

## 2. Post-Deployment Setup (Critical)
Once Render says "Live", you must perform these steps:

### Create Admin Account
1. In Render, go to your **drop-web** service.
2. Click **Shell** in the left sidebar.
3. Run: `python manage.py createsuperuser`
4. Follow prompts to create your login.

### Initialize Store Data
1. Visit `https://your-app-url.onrender.com/admin` and log in.
2. **Categories**: Create categories (e.g., "Men", "Women", "Wristwatches").
3. **Products**: Add your first products. Ensure you upload images (they will auto-save to Cloudinary).

---

## 3. Maintenance & Monitoring
- **Error Tracking**: Log in to [Sentry.io](https://sentry.io) to see if users are experiencing crashes.
- **Real-time Logs**: Monitor background tasks (like emails) via the **drop-worker** logs in Render.
- **Database Management**: Use the **drop-db** tab in Render to view your PostgreSQL backups.

---

## 4. Scaling for the Future
- **Domain**: Add a custom domain in Render Settings (e.g., `www.mystore.com`).
- **Plan Upgrade**: The "Free" database on Render expires after 90 days. Upgrade to the **Starter ($7/mo)** plan before then to keep your data permanently.

---

**Generated on:** May 2026
**Status:** Production Ready ✅
