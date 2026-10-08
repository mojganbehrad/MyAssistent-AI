import sys
import os
import webbrowser
import threading
import time
import requests
import json
from flask import Flask, jsonify, render_template, request
from storage import (
    load_items, add_item, update_item, delete_item, find_items_by_text,
    get_note, set_note,
    load_tasks, add_task, update_task, toggle_task, delete_task
)
from datetime import date, datetime, timedelta
from collections import Counter

def resource_path(relative_path):
    if hasattr(sys, "_MEIPASS"):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

app = Flask(
    __name__,
    template_folder=resource_path("templates"),
    static_folder=resource_path("static")
)

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llama3.2"
WORKDAY_START = 9   # 09:00
WORKDAY_END = 18    # 18:00

def ask_ollama(prompt, max_tokens=200):
    response = requests.post(OLLAMA_URL, json={
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": max_tokens}
    })
    return response.json()["response"]

def extract_json(raw_text):
    start = raw_text.find("{")
    end = raw_text.rfind("}") + 1
    return json.loads(raw_text[start:end])

def to_minutes(hhmm):
    """'14:30' -> 870 (minutes since midnight). Returns None if hhmm is falsy."""
    if not hhmm:
        return None
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)

def duration_hours(item):
    s, e = to_minutes(item.get("start_time")), to_minutes(item.get("end_time"))
    if s is None or e is None or e <= s:
        return 0
    return round((e - s) / 60, 2)

def find_conflicts(date_str, start_time, end_time, ignore_id=None):
    """Return other items on the same date whose time range overlaps."""
    if not start_time or not end_time:
        return []
    s1, e1 = to_minutes(start_time), to_minutes(end_time)
    conflicts = []
    for item in load_items():
        if item["date"] != date_str or item["id"] == ignore_id:
            continue
        s2, e2 = to_minutes(item.get("start_time")), to_minutes(item.get("end_time"))
        if s2 is None or e2 is None:
            continue
        if s1 < e2 and s2 < e1:  # ranges overlap
            conflicts.append({"id": item["id"], "text": item["text"],
                               "start_time": item["start_time"], "end_time": item["end_time"]})
    return conflicts

# ---------- Never let the browser cache API responses ----------
@app.after_request
def no_cache(response):
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response

@app.route("/")
def home():
    return render_template("calendar.html")

# ---------- Items ----------
@app.route("/api/items", methods=["GET", "POST"])
def api_items():
    if request.method == "POST":
        data = request.get_json()
        new_item = add_item(
            data["text"], data["date"], data["category"], data["icon"], data["color"],
            data.get("reminder_days", 1), data.get("start_time"), data.get("end_time")
        )
        conflicts = find_conflicts(new_item["date"], new_item.get("start_time"),
                                    new_item.get("end_time"), ignore_id=new_item["id"])
        return jsonify({"item": new_item, "conflicts": conflicts})
    return jsonify(load_items())

@app.route("/api/items/<int:item_id>", methods=["PUT", "DELETE"])
def api_item_detail(item_id):
    if request.method == "DELETE":
        delete_item(item_id)
        return jsonify({"status": "deleted"})
    data = request.get_json()
    updated = update_item(item_id, **data)
    conflicts = find_conflicts(updated["date"], updated.get("start_time"),
                                updated.get("end_time"), ignore_id=item_id)
    return jsonify({"item": updated, "conflicts": conflicts})

# ---------- AI: quick add ----------
@app.route("/api/quick-add", methods=["POST"])
def quick_add():
    sentence = request.get_json()["sentence"]
    today = date.today().isoformat()

    prompt = f"""Today's date is {today}.
Read this sentence and output ONLY a JSON object, nothing else, no explanation:
"{sentence}"

The JSON must have exactly these keys:
- text: short description of the task
- date: YYYY-MM-DD (figure out the real date from today's date)
- start_time: "HH:MM" 24-hour format if a time is mentioned or implied, otherwise null
- end_time: "HH:MM" 24-hour format (assume 1 hour after start if not stated), otherwise null
- category: either "personal" or "network"
- icon: one of coffee, gift, shield, lock, video, landmark, calendar
- color: a hex color. Use #38bdf8, #ec4899 or #a78bfa for personal. Use #3b5bdb, #fb923c or #f87171 for network.
"""
    parsed = extract_json(ask_ollama(prompt))
    new_item = add_item(
        parsed["text"], parsed["date"], parsed["category"], parsed["icon"], parsed["color"],
        1, parsed.get("start_time"), parsed.get("end_time")
    )
    conflicts = find_conflicts(new_item["date"], new_item.get("start_time"),
                                new_item.get("end_time"), ignore_id=new_item["id"])
    return jsonify({"item": new_item, "conflicts": conflicts})

# ---------- AI: edit ----------
@app.route("/api/edit", methods=["POST"])
def edit_item():
    instruction = request.get_json()["instruction"]
    today = date.today().isoformat()
    items = load_items()
    listing = [{"id": i["id"], "text": i["text"], "date": i["date"],
                "start_time": i.get("start_time"), "end_time": i.get("end_time")} for i in items]

    prompt = f"""Today's date is {today}.
Here is the user's current calendar items:
{json.dumps(listing, ensure_ascii=False)}

The user wants this change: "{instruction}"

Figure out which item (by id) they mean, and what should change.
Output ONLY a JSON object with these keys:
- id: the id of the item to change (integer), or null if you cannot confidently match one
- updates: an object with only the fields that should change. Allowed fields: text, date, category, icon, color, reminder_days, start_time, end_time. date must be YYYY-MM-DD, times must be "HH:MM".
"""
    parsed = extract_json(ask_ollama(prompt, max_tokens=150))
    if not parsed.get("id"):
        return jsonify({"status": "not_found"}), 404
    updated = update_item(parsed["id"], **parsed.get("updates", {}))
    conflicts = find_conflicts(updated["date"], updated.get("start_time"),
                                updated.get("end_time"), ignore_id=updated["id"])
    return jsonify({"status": "ok", "item": updated, "conflicts": conflicts})

# ---------- AI: ask ----------
@app.route("/api/ask", methods=["POST"])
def ask():
    question = request.get_json()["question"]
    today_date = date.today()
    today = today_date.isoformat()
    window_start = (today_date - timedelta(days=30)).isoformat()
    window_end = (today_date + timedelta(days=60)).isoformat()
    items = [i for i in load_items() if window_start <= i["date"] <= window_end]

    prompt = f"""Today's date is {today}.
Here is a slice of the user's calendar data as JSON (only nearby dates):
{json.dumps(items, ensure_ascii=False)}

The user asks: "{question}"

Answer in one short, friendly sentence based only on the data above.
If nothing matches, say so clearly. Output plain text only, no JSON.
"""
    answer = ask_ollama(prompt, max_tokens=60)
    return jsonify({"answer": answer.strip()})

# ---------- Notes ----------
@app.route("/api/notes/<key>", methods=["GET", "POST"])
def api_note(key):
    if request.method == "POST":
        text = request.get_json()["text"]
        set_note(key, text)
        return jsonify({"status": "ok"})
    return jsonify({"text": get_note(key)})

# ---------- Monthly report ----------
@app.route("/api/report")
def monthly_report():
    year = int(request.args.get("year"))
    month = int(request.args.get("month"))
    prefix = f"{year}-{str(month).zfill(2)}"

    items = [i for i in load_items() if i["date"].startswith(prefix)]
    note = get_note(f"month:{prefix}")

    total_hours = round(sum(duration_hours(i) for i in items), 1)
    day_counts = Counter(i["date"] for i in items)
    busiest = day_counts.most_common(3)

    stats = {
        "total_events": len(items),
        "total_hours": total_hours,
        "busiest_days": busiest,
        "items": [{"text": i["text"], "date": i["date"],
                   "start_time": i.get("start_time"), "end_time": i.get("end_time")} for i in items]
    }

    prompt = f"""Here is this month's calendar data:
{json.dumps(stats, ensure_ascii=False)}

Here are the user's notes for this month: "{note}"

Write a short summary covering: the most important-looking events, the main topics/themes you notice
in the titles and notes, and a one-line take on how busy the month looks.
3-5 sentences, plain text only, no headers, no JSON.
"""
    summary = ask_ollama(prompt, max_tokens=220)

    return jsonify({
        "total_events": len(items),
        "total_hours": total_hours,
        "busiest_days": busiest,
        "notes_summary": note,
        "summary": summary.strip()
    })

# ---------- Schedule analysis (busiest days / overloaded days) ----------
@app.route("/api/analyze")
def analyze():
    year = int(request.args.get("year"))
    month = int(request.args.get("month"))
    prefix = f"{year}-{str(month).zfill(2)}"
    items = [i for i in load_items() if i["date"].startswith(prefix)]

    hours_per_day = Counter()
    count_per_day = Counter()
    for i in items:
        count_per_day[i["date"]] += 1
        hours_per_day[i["date"]] += duration_hours(i)

    overloaded = [{"date": d, "hours": round(h, 1)} for d, h in hours_per_day.items() if h >= 5]
    busiest = sorted(count_per_day.items(), key=lambda x: -x[1])[:3]

    by_category = Counter(i["category"] for i in items)

    return jsonify({
        "busiest_days": busiest,
        "overloaded_days": sorted(overloaded, key=lambda x: -x["hours"]),
        "by_category": dict(by_category)
    })

# ---------- Free time finder ----------
def free_slots_on(date_str, duration_hours_needed):
    items = [i for i in load_items()
             if i["date"] == date_str and i.get("start_time") and i.get("end_time")]
    busy = sorted([(to_minutes(i["start_time"]), to_minutes(i["end_time"])) for i in items])

    day_start = WORKDAY_START * 60
    day_end = WORKDAY_END * 60
    need = int(duration_hours_needed * 60)

    cursor = day_start
    for s, e in busy:
        if s - cursor >= need:
            return (cursor, cursor + need)
        cursor = max(cursor, e)
    if day_end - cursor >= need:
        return (cursor, cursor + need)
    return None

def minutes_to_hhmm(m):
    return f"{m // 60:02d}:{m % 60:02d}"

@app.route("/api/free-time", methods=["POST"])
def free_time():
    sentence = request.get_json()["sentence"]
    today = date.today().isoformat()

    prompt = f"""Today's date is {today}.
From this sentence, extract the target date and the requested duration in hours:
"{sentence}"

Output ONLY a JSON object: {{"date": "YYYY-MM-DD", "duration_hours": number}}
"""
    parsed = extract_json(ask_ollama(prompt, max_tokens=80))
    slot = free_slots_on(parsed["date"], parsed["duration_hours"])

    if not slot:
        return jsonify({"found": False,
                         "message": f"No free {parsed['duration_hours']}-hour slot found on {parsed['date']} during work hours."})

    return jsonify({
        "found": True,
        "date": parsed["date"],
        "start_time": minutes_to_hhmm(slot[0]),
        "end_time": minutes_to_hhmm(slot[1]),
        "message": f"Free from {minutes_to_hhmm(slot[0])} to {minutes_to_hhmm(slot[1])} on {parsed['date']}."
    })

# ---------- Focus time suggestion (next 7 days) ----------
@app.route("/api/focus-suggest")
def focus_suggest():
    today = date.today()
    best = None
    for offset in range(7):
        d = (today + timedelta(days=offset)).isoformat()
        slot = free_slots_on(d, 2)  # look for a 2-hour block
        if slot:
            best = (d, slot)
            break
    if not best:
        return jsonify({"found": False, "message": "No clear 2-hour focus block in the next 7 days."})
    d, (s, e) = best
    return jsonify({"found": True, "date": d, "start_time": minutes_to_hhmm(s), "end_time": minutes_to_hhmm(e),
                     "message": f"Best focus block: {d}, {minutes_to_hhmm(s)}–{minutes_to_hhmm(e)}."})

# ---------- Command bar (Ctrl+K) ----------
@app.route("/api/command", methods=["POST"])
def command():
    text = request.get_json()["text"]
    today = date.today().isoformat()

    prompt = f"""Today's date is {today}. Classify this command: "{text}"

Output ONLY a JSON object with:
- action: one of "add", "edit", "delete", "ask", "search", "prev_month", "next_month", "today"
- payload: a short string with the relevant part of the command (empty string if not needed)
"""
    parsed = extract_json(ask_ollama(prompt, max_tokens=100))
    action = parsed.get("action")
    payload = parsed.get("payload", "")

    if action == "add":
        return quick_add_internal(payload or text)
    if action == "edit":
        return edit_internal(payload or text)
    if action == "ask":
        return ask_internal(payload or text)
    if action == "search":
        matches = find_items_by_text(payload or text)
        return jsonify({"action": "search", "results": matches})
    if action in ("prev_month", "next_month", "today"):
        return jsonify({"action": action})

    return jsonify({"action": "ask", "answer": "Sorry, I didn't understand that."})

def quick_add_internal(sentence):
    with app.test_request_context(json={"sentence": sentence}):
        return quick_add()

def edit_internal(instruction):
    with app.test_request_context(json={"instruction": instruction}):
        return edit_item()

def ask_internal(question):
    with app.test_request_context(json={"question": question}):
        return ask()

# ---------- Tasks (Todo) ----------
@app.route("/api/tasks", methods=["GET", "POST"])
def api_tasks():
    if request.method == "POST":
        d = request.get_json()
        new_task = add_task(
            d["title"], d.get("description", ""), d.get("priority", "medium"),
            d.get("due_date"), d.get("category", "personal"),
            d.get("duration_minutes"), d.get("recurring")
        )
        return jsonify(new_task)
    return jsonify(load_tasks())

@app.route("/api/tasks/<int:task_id>", methods=["PUT", "DELETE"])
def api_task_detail(task_id):
    if request.method == "DELETE":
        delete_task(task_id)
        return jsonify({"status": "deleted"})
    updated = update_task(task_id, **request.get_json())
    return jsonify(updated)

@app.route("/api/tasks/<int:task_id>/toggle", methods=["POST"])
def api_task_toggle(task_id):
    updated = toggle_task(task_id)
    return jsonify(updated)

# ---------- AI capture: decide Task vs Calendar Event ----------
@app.route("/api/capture", methods=["POST"])
def capture():
    sentence = request.get_json()["sentence"]
    today = date.today().isoformat()

    prompt = f"""Today's date is {today}.
Decide whether this sentence describes a CALENDAR EVENT (has a specific date/time to be somewhere
or meet someone) or a TASK (a to-do item, no fixed time slot, e.g. "buy groceries", "read 10 pages").

Sentence: "{sentence}"

Output ONLY a JSON object:
If it's an event:
{{"kind": "event", "text": "...", "date": "YYYY-MM-DD", "start_time": "HH:MM or null",
  "end_time": "HH:MM or null", "category": "personal or network",
  "icon": "one of coffee, gift, shield, lock, video, landmark, calendar",
  "color": "#38bdf8 #ec4899 #a78bfa for personal, #3b5bdb #fb923c #f87171 for network"}}

If it's a task:
{{"kind": "task", "title": "...", "priority": "low, medium or high", "due_date": "YYYY-MM-DD or null",
  "category": "personal or network", "duration_minutes": number or null}}
"""
    parsed = extract_json(ask_ollama(prompt, max_tokens=200))

    if parsed["kind"] == "event":
        new_item = add_item(parsed["text"], parsed["date"], parsed["category"],
                             parsed["icon"], parsed["color"], 1,
                             parsed.get("start_time"), parsed.get("end_time"))
        conflicts = find_conflicts(new_item["date"], new_item.get("start_time"),
                                    new_item.get("end_time"), ignore_id=new_item["id"])
        return jsonify({"kind": "event", "item": new_item, "conflicts": conflicts})

    new_task = add_task(parsed["title"], "", parsed.get("priority", "medium"),
                         parsed.get("due_date"), parsed.get("category", "personal"),
                         parsed.get("duration_minutes"))
    return jsonify({"kind": "task", "task": new_task})

# ---------- Today dashboard ----------
@app.route("/api/today-dashboard")
def today_dashboard():
    today = date.today().isoformat()
    tasks_today = [t for t in load_tasks() if t["due_date"] == today]
    done_count = sum(1 for t in tasks_today if t["done"])
    progress = round(done_count / len(tasks_today) * 100) if tasks_today else 0

    priority_order = {"high": 0, "medium": 1, "low": 2}
    pending = [t for t in tasks_today if not t["done"]]
    pending.sort(key=lambda t: priority_order.get(t["priority"], 1))
    top_task = pending[0]["title"] if pending else None

    slot = free_slots_on(today, 1)  # is there at least 1 free hour left today?
    free_hours_available = slot is not None

    return jsonify({
        "total_today": len(tasks_today),
        "done_today": done_count,
        "progress_percent": progress,
        "top_task": top_task,
        "has_free_time_today": free_hours_available,
        "tasks": tasks_today
    })

# ---------- Background reminders ----------
def check_reminders():
    while True:
        today = date.today()
        for item in load_items():
            try:
                event_date = date.fromisoformat(item["date"])
            except ValueError:
                continue
            days_before = item.get("reminder_days", 1)
            fire_date = event_date - timedelta(days=days_before)
            if fire_date == today and item.get("notified_date") != today.isoformat():
                try:
                    from plyer import notification
                    notification.notify(title="Upcoming: " + item["text"],
                                         message=f"On {item['date']}", timeout=10)
                except Exception as e:
                    print("Notification failed:", e)
                update_item(item["id"], notified_date=today.isoformat())
        time.sleep(3600)

def open_browser():
    webbrowser.open("http://127.0.0.1:5000")

if __name__ == "__main__":
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        threading.Timer(1.5, open_browser).start()
    else:
        threading.Thread(target=check_reminders, daemon=True).start()
    app.run(debug=True)
