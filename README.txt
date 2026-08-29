NeedBeacon Web MVP V2

Key validation fix:
- The user asks for the best 5/10/20 results.
- The app discovers and analyzes up to 50 restaurants first.
- It ranks the full analyzed pool and only then shows the best opportunities.
- Analysis is parallelized to reduce waiting time.
- This MVP is intentionally focused on Website Design -> Restaurants, because that is the use case actually validated so far.

Run:
python app.py
Open:
http://127.0.0.1:5000
