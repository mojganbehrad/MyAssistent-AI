import json
import os

FILENAME = "data.json"
NOTES_FILENAME = "notes.json"

# ---------- Items (events) ----------

def load_items():
    if not os.path.exists(FILENAME):
        return []
    with open(FILENAME, "r", encoding="utf-8") as f:
        return json.load(f)

def save_items(items):
    with open(FILENAME, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

def next_id(items):
    if not items:
        return 1
    return max(item["id"] for item in items) + 1

def add_item(text, date, category, icon, color,
             reminder_days=1, start_time=None, end_time=None):
    items = load_items()
    item = {
        "id": next_id(items),
        "text": text,
        "date": date,
        "category": category,
        "icon": icon,
        "color": color,
        "reminder_days": reminder_days,
        "notified_date": None,
        "start_time": start_time,   # "HH:MM" or None
        "end_time": end_time        # "HH:MM" or None
    }
    items.append(item)
    save_items(items)
    return item

def update_item(item_id, **fields):
    items = load_items()
    updated = None
    for item in items:
        if item["id"] == item_id:
            item.update(fields)
            updated = item
    save_items(items)
    return updated

def delete_item(item_id):
    items = load_items()
    items = [item for item in items if item["id"] != item_id]
    save_items(items)

def find_items_by_text(keyword):
    items = load_items()
    keyword = keyword.lower()
    return [i for i in items if keyword in i["text"].lower()]


# ---------- Notes (day / month / year) ----------

def load_notes():
    if not os.path.exists(NOTES_FILENAME):
        return {}
    with open(NOTES_FILENAME, "r", encoding="utf-8") as f:
        return json.load(f)

def save_notes(notes):
    with open(NOTES_FILENAME, "w", encoding="utf-8") as f:
        json.dump(notes, f, ensure_ascii=False, indent=2)

def get_note(key):
    notes = load_notes()
    return notes.get(key, "")

def set_note(key, text):
    notes = load_notes()
    notes[key] = text
    save_notes(notes)


# ---------- Tasks (Todo — separate from calendar events) ----------

TASKS_FILENAME = "tasks.json"

def load_tasks():
    if not os.path.exists(TASKS_FILENAME):
        return []
    with open(TASKS_FILENAME, "r", encoding="utf-8") as f:
        return json.load(f)

def save_tasks(tasks):
    with open(TASKS_FILENAME, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)

def next_task_id(tasks):
    if not tasks:
        return 1
    return max(t["id"] for t in tasks) + 1

def add_task(title, description="", priority="medium", due_date=None,
             category="personal", duration_minutes=None, recurring=None):
    tasks = load_tasks()
    task = {
        "id": next_task_id(tasks),
        "title": title,
        "description": description,
        "priority": priority,       # "low" | "medium" | "high"
        "due_date": due_date,       # "YYYY-MM-DD" or None
        "category": category,       # "personal" | "network"
        "duration_minutes": duration_minutes,
        "subtasks": [],             # [{"text": "...", "done": false}]
        "recurring": recurring,     # None | "daily" | "weekly"
        "done": False
    }
    tasks.append(task)
    save_tasks(tasks)
    return task

def update_task(task_id, **fields):
    tasks = load_tasks()
    updated = None
    for t in tasks:
        if t["id"] == task_id:
            t.update(fields)
            updated = t
    save_tasks(tasks)
    return updated

def toggle_task(task_id):
    tasks = load_tasks()
    updated = None
    for t in tasks:
        if t["id"] == task_id:
            t["done"] = not t["done"]
            updated = t
    save_tasks(tasks)
    return updated

def delete_task(task_id):
    tasks = load_tasks()
    tasks = [t for t in tasks if t["id"] != task_id]
    save_tasks(tasks)
