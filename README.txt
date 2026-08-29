NeedBeacon PUBLIC EARLY ACCESS

Purpose: lightweight public validation site for Render Free. It DOES NOT run the heavy 50-business scanner.

Render:
Build Command: pip install -r requirements.txt
Start Command: gunicorn app:app

Recommended environment variable:
WAITLIST_ADMIN_KEY = choose a long private password/token

View signups privately:
https://needbeacon.onrender.com/admin/waitlist?key=YOUR_PRIVATE_KEY

IMPORTANT: Render Free local filesystem is ephemeral. This waitlist is suitable for initial validation only; meaningful signups should be copied/exported before redeploys/restarts. For durable production storage, connect a database or form/email service later.
