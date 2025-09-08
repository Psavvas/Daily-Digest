import os
import json
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

try:
    from icalendar import Calendar
    from dateutil import parser as dateparser
except Exception as e:
    print("Missing dependencies. Please run: pip install -r requirements.txt")
    raise

# -------------- Helpers --------------

def load_config():
    here = os.path.dirname(os.path.abspath(__file__))
    cfg_path = os.path.join(here, "config.json")
    with open(cfg_path, "r", encoding="utf-8") as f:
        return json.load(f)

def human_time(dt, tz_str):
    tz = ZoneInfo(tz_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc).astimezone(tz)
    else:
        dt = dt.astimezone(tz)
    return dt.strftime("%I:%M %p").lstrip("0")

def human_date(dt, tz_str):
    tz = ZoneInfo(tz_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc).astimezone(tz)
    else:
        dt = dt.astimezone(tz)
    return dt.strftime("%A, %B %d, %Y")

def sanitize_webcal(url):
    # iCloud public calendars often use webcal://; swap for https://
    return url.replace("webcal://", "https://")

# -------------- Data Fetchers --------------

def fetch_events(ics_urls, tz_str, start_dt, end_dt):
    events = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }
    for url in ics_urls:
        try:
            resp = requests.get(sanitize_webcal(url), headers=headers, timeout=20, verify=False)
            resp.raise_for_status()
            cal = Calendar.from_ical(resp.content)
        except Exception as e:
            logging.exception("Failed to fetch/parse ICS from %s", url)
            continue

        for component in cal.walk():
            if component.name != "VEVENT":
                continue
            summary = str(component.get("summary", "")).strip()
            location = str(component.get("location", "")).strip()
            description = str(component.get("description", "")).strip()

            dtstart = component.get("dtstart")
            dtend = component.get("dtend")

            # Handle all-day (date) vs timed (datetime)
            if hasattr(dtstart, "dt"):
                s = dtstart.dt
            else:
                continue

            if hasattr(dtend, "dt"):
                e = dtend.dt
            else:
                # assume 1 hour if missing
                if isinstance(s, datetime):
                    e = s + timedelta(hours=1)
                else:
                    e = s

            # Convert date-only to a datetime window within the day in tz
            tz = ZoneInfo(tz_str)
            if isinstance(s, datetime):
                s_dt = s if s.tzinfo else s.replace(tzinfo=timezone.utc)
            else:
                # date
                s_dt = datetime(s.year, s.month, s.day, 0, 0, tzinfo=tz)
            if isinstance(e, datetime):
                e_dt = e if e.tzinfo else e.replace(tzinfo=timezone.utc)
            else:
                e_dt = datetime(e.year, e.month, e.day, 23, 59, tzinfo=tz)

            # Compare in a common tz
            s_cmp = s_dt.astimezone(ZoneInfo("UTC"))
            e_cmp = e_dt.astimezone(ZoneInfo("UTC"))
            if e_cmp < start_dt.astimezone(ZoneInfo("UTC")) or s_cmp > end_dt.astimezone(ZoneInfo("UTC")):
                continue

            events.append({
                "title": summary or "(No title)",
                "location": location,
                "description": description,
                "start": s_dt.astimezone(ZoneInfo(tz_str)).isoformat(),
                "end": e_dt.astimezone(ZoneInfo(tz_str)).isoformat(),
                "all_day": not isinstance(dtstart.dt, datetime),
            })
    # sort by start time
    events.sort(key=lambda x: x["start"])
    return events

def load_reminders(json_path, tz_str, end_dt):
    items = []
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        logging.warning("Reminders JSON not found at %s", json_path)
        return items
    except Exception:
        logging.exception("Failed to read reminders JSON")
        return items

    tz = ZoneInfo(tz_str)
    now = datetime.now(tz)

    reminders_raw = data.get("reminders", [])
    reminders_list = []
    # If reminders is a string (old/alternate format), parse each JSON object per line
    if isinstance(reminders_raw, str):
        for line in reminders_raw.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                # If any fields contain multiple values separated by \n, split them
                titles = r.get("title", "").split("\n")
                dues = r.get("due", "").split("\n")
                priorities = r.get("priority", "").split("\n")
                notes = r.get("notes", "").split("\n")
                lists = r.get("list", "").split("\n")
                max_len = max(len(titles), len(dues), len(priorities), len(notes), len(lists))
                for i in range(max_len):
                    reminders_list.append({
                        "title": titles[i] if i < len(titles) else "",
                        "due": dues[i] if i < len(dues) else "",
                        "priority": priorities[i] if i < len(priorities) else "",
                        "notes": notes[i] if i < len(notes) else "",
                        "list": lists[i] if i < len(lists) else ""
                    })
            except Exception:
                continue
    elif isinstance(reminders_raw, list):
        reminders_list = reminders_raw
    else:
        # fallback: try to treat as a single dict
        if isinstance(reminders_raw, dict):
            reminders_list = [reminders_raw]

    seen = set()
    for r in reminders_list:
        title = r.get("title") or "(Untitled reminder)"
        due_raw = r.get("due")
        list_name = r.get("list") or ""
        priority = r.get("priority") or ""
        notes = r.get("notes") or ""

        due_dt = None
        if due_raw:
            try:
                due_dt = dateparser.parse(due_raw)
                if due_dt.tzinfo is None:
                    due_dt = due_dt.replace(tzinfo=timezone.utc).astimezone(tz)
                else:
                    due_dt = due_dt.astimezone(tz)
            except Exception:
                due_dt = None

        include = True
        # If due date provided, include only if due before end_dt
        if due_dt is not None and due_dt > end_dt:
            include = False

        # Create a tuple of key fields to identify duplicates
        key = (title.strip().lower(), due_dt.isoformat() if due_dt else None, list_name.strip().lower())
        if include and key not in seen:
            seen.add(key)
            items.append({
                "title": title,
                "list": list_name,
                "priority": priority,
                "notes": notes,
                "due": due_dt.isoformat() if due_dt else None
            })

    # sort: due date first, None at end
    items.sort(key=lambda x: (x["due"] is None, x["due"] or ""))
    return items

def fetch_weather(api_key, lat, lon, units="imperial"):
    try:
        url = "https://api.openweathermap.org/data/2.5/weather"
        params = {"lat": lat, "lon": lon, "appid": api_key, "units": units}
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        temp = round(data["main"]["temp"])
        feels = round(data["main"]["feels_like"])
        desc = data["weather"][0]["description"].title()
        wind = round(data["wind"].get("speed", 0))
        city = data.get("name", "")
        return {"temp": temp, "feels": feels, "desc": desc, "wind": wind, "city": city}
    except Exception:
        logging.exception("Weather fetch failed")
        return None

def fetch_quote(source="zenquotes"):
    # primary: ZenQuotes
    if source == "zenquotes":
        try:
            r = requests.get("https://zenquotes.io/api/random", timeout=10)
            r.raise_for_status()
            js = r.json()
            q = js[0]["q"].strip()
            a = js[0]["a"].strip()
            return f"“{q}” — {a}"
        except Exception:
            logging.exception("Quote fetch failed")
    # fallback quotes
    FALLBACK = [
        "“We are what we repeatedly do. Excellence, then, is not an act, but a habit.” — Will Durant",
        "“Do the hard things—especially when you don’t feel like it.”",
        "“Simplicity is the ultimate sophistication.” — Leonardo da Vinci",
        "“The secret of getting ahead is getting started.” — Mark Twain",
    ]
    return FALLBACK[0]

# -------------- Email --------------

def send_email(smtp_cfg, from_addr, to_addrs, subject, html_body):
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = from_addr
    msg['To'] = ", ".join(to_addrs)
    part = MIMEText(html_body, 'html')
    msg.attach(part)

    with smtplib.SMTP(smtp_cfg["server"], smtp_cfg["port"]) as server:
        server.starttls()
        server.login(smtp_cfg["username"], smtp_cfg["password"])
        server.sendmail(from_addr, to_addrs, msg.as_string())

# -------------- HTML --------------

def build_html(tz_str, date_title, reminders, events, weather, quote):
    # Minimal, clean styling inline for email clients
    style = """
    <style>
        body { font-family: 'Segoe UI', 'Roboto', Arial, sans-serif; background: #f4f6fb; color: #22223b; margin: 0; }
        .wrap { max-width: 600px; margin: 32px auto; background: #fff; border-radius: 18px; box-shadow: 0 4px 24px #0001; padding: 32px 28px 24px 28px; }
        h1 { font-size: 2rem; margin: 0 0 18px; font-weight: 700; color: #3a3a5a; letter-spacing: 0.5px; }
        h2 { font-size: 1.15rem; margin: 24px 0 10px; color: #4f4f7a; border-left: 4px solid #a5b4fc; padding-left: 10px; font-weight: 600; }
        ul { margin: 10px 0 0 22px; padding: 0; }
        li { margin-bottom: 7px; line-height: 1.5; }
        .muted { color: #8a8fa3; font-size: 0.97em; }
        .card { background: #f7f8fd; border-radius: 12px; box-shadow: 0 1px 4px #0001; padding: 18px 18px 12px 18px; margin-top: 18px; }
        .quote { font-style: italic; color: #5b5b7a; font-size: 1.08em; }
        .event-time { font-weight: 600; color: #3b82f6; }
        .all-day { background: #e0e7ff; color: #37377a; padding: 2px 10px; border-radius: 8px; font-size: 0.98em; margin-right: 6px; }
        .section { margin-bottom: 18px; }
        .greeting { font-size: 1.13rem; margin-bottom: 18px; color: #3a3a5a; }
        .footer { color: #b0b3c6; font-size: 0.95em; margin-top: 22px; text-align: center; }
    </style>
    """
    html = [f"<!doctype html><html><head>{style}</head><body><div class='wrap'>"]
    # Header first, then greeting with day
    weekday = datetime.now(ZoneInfo(tz_str)).strftime('%A')
    html.append(f"<h1>Daily Digest — {date_title}</h1>")
    html.append(f"<div class='greeting'>Hi, Paul. Happy {weekday}! This is your daily digest.</div>")

    # Weather
    html.append("<div class='card section'>")
    html.append("<h2>Weather</h2>")
    if weather:
        city = f" — {weather.get('city')}" if weather.get('city') else ""
        html.append(f"<div><strong>{weather['desc']}</strong>{city}<br>")
        html.append(f"Temp {weather['temp']}°, feels like {weather['feels']}°; wind {weather['wind']}.")
        html.append("</div>")
    else:
        html.append("<div class='muted'>Weather unavailable.</div>")
    html.append("</div>")

    # Reminders
    html.append("<div class='card section'>")
    html.append("<h2>Upcoming Tasks</h2>")
    if reminders:
        html.append("<ul>")
        for r in reminders:
            due = ""
            if r["due"]:
                dt = datetime.fromisoformat(r["due"])
                due = f" <span class='muted'>(due {human_time(dt, tz_str)})</span>"
            listname = f" <span class='muted'>[{r['list']}]</span>" if r["list"] else ""
            html.append(f"<li><span style='font-weight:500'>{r['title']}</span>{listname}{due}</li>")
        html.append("</ul>")
    else:
        html.append("<div class='muted'>No upcoming tasks.</div>")
    html.append("</div>")

    # Events
    html.append("<div class='card section'>")
    html.append("<h2>Today's Events</h2>")
    if events:
        html.append("<ul>")
        for e in events:
            start = datetime.fromisoformat(e["start"])
            end = datetime.fromisoformat(e["end"])
            if e["all_day"]:
                when = "All‑day"
                badge = f"<span class='all-day'>{when}</span>"
                time_range = ""
            else:
                start_str = human_time(start, tz_str)
                end_str = human_time(end, tz_str)
                badge = f"<span class='event-time'>{start_str}–{end_str}</span>"
                time_range = ""
            loc = f" <span class='muted'>— {e['location']}</span>" if e['location'] else ""
            html.append(f"<li>{badge} <span style='font-weight:500'>{e['title']}</span>{loc}</li>")
        html.append("</ul>")
    else:
        html.append("<div class='muted'>No events today.</div>")
    html.append("</div>")

    # Quote
    html.append("<div class='card section'>")
    html.append("<h2>Motivation</h2>")
    html.append(f"<div class='quote'>{quote}</div>")
    html.append("</div>")

    html.append("<div class='footer'>Generated automatically.</div>")
    html.append("</div></body></html>")
    return "".join(html)

# -------------- Main --------------

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    cfg = load_config()
    tz_str = cfg["digest"].get("time_zone", "America/New_York")
    tz = ZoneInfo(tz_str)
    days = int(cfg["digest"].get("days_ahead", 1))
    now = datetime.now(tz)
    start_dt = datetime(now.year, now.month, now.day, 0, 0, tzinfo=tz)
    end_dt = start_dt + timedelta(days=days) - timedelta(seconds=1)

    # Data
    reminders = load_reminders(cfg["reminders"]["json_path"], tz_str, end_dt)
    events = fetch_events(cfg["calendar"]["ics_urls"], tz_str, start_dt, end_dt)
    weather = fetch_weather(cfg["weather"]["api_key"], cfg["weather"]["lat"], cfg["weather"]["lon"], cfg["weather"].get("units", "imperial"))
    quote = fetch_quote(cfg.get("quote", {}).get("source", "zenquotes"))


    date_title = human_date(now, tz_str)
    subject = f"{cfg['digest'].get('subject_prefix', '[Daily Digest]')} {date_title}"

    html = build_html(tz_str, date_title, reminders, events, weather, quote)

    if not cfg["digest"].get("send_empty", True):
        if not any([reminders, events, weather, quote]):
            logging.info("Nothing to send and send_empty is False; exiting.")
            return

    send_email(cfg["smtp"], cfg["email"]["from"], cfg["email"]["to"], subject, html)
    logging.info("Digest sent.")

if __name__ == "__main__":
    main()
