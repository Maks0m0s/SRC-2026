import utime
import network
import uasyncio as asyncio
from machine import Pin, PWM
from tm1637 import TM1637
import json
import gc

utime.sleep(2)

MY_SSID = "SRC-2026"
MY_PASSWORD = "123456789"

ap = network.WLAN(network.AP_IF)

def start_ap():
    ap.active(False)
    utime.sleep_ms(300)

    ap.active(True)
    ap.config(essid=MY_SSID, password=MY_PASSWORD)

    utime.sleep_ms(200)

    try:
        ap.ifconfig(("192.168.4.1", "255.255.255.0", "192.168.4.1", "8.8.8.8"))
        print("✅ AP running:", ap.ifconfig())
    except Exception as e:
        print("⚠️ AP ifconfig error:", e)

def refresh_time():
    global time_configured, current_h, current_m, current_date

    current_h = 0
    current_m = 0
    current_date = '2026-01-01'
    time_configured = False
    print('Time refreshed.')

# ==== JSON DATA ====
DATA_FILE = "data.json"

def save_data():
    try:
        data = {
            "alarms": [
                {
                    "uid": a.uid,
                    "h": a.h,
                    "m": a.m,
                    "name": a.name,
                    "repeat": a.repeat,
                    "enabled": a.enabled,
                    "triggered_today": a.triggered_today
                }
                for a in alarms_manager.alarms
            ],

            "important_days": [
                {
                    "uid": d.uid,
                    "name": d.name,
                    "date": d.date,
                    "color": d.color,
                }
                for d in daysBase.days
            ],
        }

        with open(DATA_FILE + ".tmp", "w") as f:
            json.dump(data, f)

        import os
        os.rename(DATA_FILE + ".tmp", DATA_FILE)

        print("✅ Data saved")

    except Exception as e:
        print("❌ Save error:", e)

def load_data():
    try:
        with open(DATA_FILE, "r") as f:
            raw = json.load(f)
    except:
        print("⚠️ No data file, starting fresh")
        return
    # ===== ALARMS =====
    alarms_manager.alarms.clear()
    Alarm._next_id = 0

    for a in raw.get("alarms", []):
        alarm = Alarm(
            a["h"], a["m"], a["name"], a["repeat"], a["enabled"]
        )
        alarm.uid = a["uid"]
        alarm.triggered_today = a["triggered_today"]
        alarms_manager.alarms.append(alarm)
        Alarm._next_id = max(Alarm._next_id, alarm.uid + 1)

    # ===== IMPORTANT DAYS =====
    daysBase.days.clear()
    ImportantDay._next_id = 0

    for d in raw.get("important_days", []):
        day = ImportantDay(
            d["name"], d["date"], d["color"]
        )
        day.uid = d["uid"]
        daysBase.days.append(day)
        ImportantDay._next_id = max(ImportantDay._next_id, day.uid + 1)

    print("✅ Data loaded")

# ==== DISPLAY PARAMETERS ====
brightness = 3
display_on = True
display_button = Pin(17, Pin.IN, Pin.PULL_UP)

# ==== 4-Digit Display ====
CLK = Pin(23)
DIO = Pin(22)
display = TM1637(CLK, DIO)
display.brightness = brightness

# ==== ALARM PINOUT ====
base_epoch = 0
base_ticks = 0

current_h = 0
current_m = 0
current_date = "2026-01-01"

def split_date(date_str):
    parts = date_str.split("-")
    if len(parts) != 3:
        raise ValueError("Invalid date format")
    return int(parts[0]), int(parts[1]), int(parts[2])

time_task = None
time_status = 'idle'
time_configured = False

trigger_on = False
active_alarm = None
trigger_time = 0

stop_button = Pin(19, Pin.IN, Pin.PULL_UP)

buzzer = PWM(Pin(21))
buzzer.duty(0)

led = Pin(18, Pin.OUT)

# ================= ALARM SOUND =================
async def trigger_alarm_until_stopped():
    global trigger_on, active_alarm, trigger_time

    print("🚨 Alarm ringing")

    trigger_time = utime.ticks_ms()

    while trigger_on:
        if not stop_button.value():
            break

        if not utime.ticks_diff(utime.ticks_ms(), trigger_time) > 60000:
            for freq in (1000, 1200):
                if not trigger_on or not stop_button.value():
                    break

                led.value(1)
                buzzer.freq(freq)
                buzzer.duty(512)
                await asyncio.sleep(0.25)
                led.value(0)
                buzzer.duty(0)
                await asyncio.sleep(0.1)
        else:
            break
    led.value(0)
    buzzer.duty(0)

    # 🔥 IMPORTANT PART
    if active_alarm:
        if active_alarm.repeat == "once":
            active_alarm.enabled = False   # disable once alarms
        active_alarm.triggered_today = True

    trigger_on = False
    active_alarm = None
    print("🛑 Alarm stopped")

# ==== ALARMS MANAGER CLASS====
class AlarmsManager:
    def __init__(self):
        self.alarms = []

    def add_alarm(self, alarm):
        for a in self.alarms:
            if a.name == alarm.name and a.h == alarm.h and a.m == alarm.m:
                return False
        self.alarms.append(alarm)
        save_data()
        return True

    def delete_alarm(self, alarm_id):
        self.alarms = [a for a in self.alarms if a.id() != alarm_id]
        save_data()

    def get_alarm(self, alarm_id):
        for a in self.alarms:
            if a.id() == alarm_id:
                return a
        return None

    def list_alarms(self):
        return self.alarms

    async def run(self):
        global trigger_on, active_alarm, current_h, current_m, display_on

        while True:
            if time_configured:
                for alarm in self.alarms:
                    if (
                        alarm.enabled
                        and alarm.h == current_h
                        and alarm.m == current_m
                        and not alarm.triggered_today
                        and not trigger_on
                    ):
                        trigger_on = True
                        active_alarm = alarm

                        past_display_state = display_on
                        past_brightness = brightness

                        display_power(True)
                        display_brightness(3)

                        await trigger_alarm_until_stopped()

                        # 🔁 RESTORE STATE AFTER ALARM
                        if not past_display_state:
                            display_power(False)
                        else:
                            display_power(True)
                            display_brightness(past_brightness)

                    # 🔥 DAILY RESET AT MIDNIGHT
                    if current_h == 0 and current_m == 0:
                        alarm.triggered_today = False

                await asyncio.sleep(1)
            else:
                await asyncio.sleep(0.5)

# === ALARMS OBJ ===
class Alarm:
    _next_id = 0

    def __init__(self, h, m, name="Alarm", repeat="once", enabled=True):
        self.uid = Alarm._next_id
        Alarm._next_id += 1

        self.h = h
        self.m = m
        self.name = name
        self.repeat = repeat          # "once" or "daily"
        self.enabled = enabled
        self.triggered_today = False

    def id(self):
        return str(self.uid)

# === ALARM MANAGER ===
alarms_manager = AlarmsManager()

# ===== LOAD HTML =====
def get_html(filename):
    try:
        with open(f"{filename}.html") as f:
            return f.read()
    except:
        return f"<h1>Missing {filename}.html</h1>"

def escape_html(text):
    """Escape HTML special characters"""
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    text = text.replace('"', "&quot;")
    text = text.replace("'", "&#39;")
    return text

# ===== TIME API =====

class DaysBase:
    # Max days per month (index 1 = January, 12 = December)
    DAYS_IN_MONTH = [0, 31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

    def __init__(self):
        self.days = []

    def list_days(self):
        return self.days

    def get_day(self, day_id):
        for day in self.days:
            if day.id() == str(day_id):
                return day
        return None

    def _validate_date(self, date_str):
        """Return (day, month) if valid, else None"""
        try:
            parts = date_str.split('-')
            if len(parts) != 2:
                return None
            day_num, month_num = map(int, parts)
            if not (1 <= month_num <= 12):
                return None
            if not (1 <= day_num <= self.DAYS_IN_MONTH[month_num]):
                return None
            return day_num, month_num
        except (ValueError, TypeError):
            return None

    def add_day(self, day):
        # Validate date
        if not self._validate_date(day.date):
            return None

        # Check for duplicate name
        for d in self.days:
            if d.name == day.name:
                return None

        self.days.append(day)
        save_data()
        return True

    def delete_day(self, day):
        for d in self.days:
            if d == day:
                self.days.remove(d)
                save_data()
                return True
        return None

    def edit_day(self, day, name, date, color):
        valid_date = self._validate_date(date)
        if not valid_date:
            return None

        # Update existing day
        for d in self.days:
            if d.name == day.name:
                d.name = name
                d.date = date
                d.color = color
                d.name_url = name.replace(' ', '-')
                save_data()
                return True

        return None

class ImportantDay:
    _next_id = 0

    def __init__(self, name, date, color):
        self.uid = ImportantDay._next_id
        ImportantDay._next_id += 1

        self.name = name
        self.date = date
        self.color = color
        self.name_url = self.name.replace(' ', '-')

    def id(self):
        return str(self.uid)

daysBase = DaysBase()

def days_until(event_date):
    today = current_date

    ymd = split_date(today)
    if not ymd:
        print("⚠️ Invalid current_date:", today)
        return -1, today

    y, m, d = ymd

    days = get_days(event_date, y, m, d)
    if days < 0:
        print("⚠️ Invalid event date:", event_date)
        return -1, today

    print(f'Today : {today}')
    print("{} days to {}".format(days, event_date))
    return days, today

def get_days(target_date, today_year, today_month, today_day):
    try:
        if not target_date or "-" not in target_date:
            return -1

        parts = target_date.split("-")

        # ---------- YYYY-MM-DD ----------
        if len(parts) == 3:
            _, m, d = parts

        # ---------- DD-MM ----------
        elif len(parts) == 2:
            d, m = parts

        else:
            return -1

        # Convert safely
        target_day = int(d)
        target_month = int(m)

        # Basic validation
        if not (1 <= target_month <= 12 and 1 <= target_day <= 31):
            return -1

        target_year = today_year

        # If already passed this year → next year
        if (target_month, target_day) < (today_month, today_day):
            target_year += 1

        today_ts = utime.mktime(
            (today_year, today_month, today_day, 0, 0, 0, 0, 0)
        )
        target_ts = utime.mktime(
            (target_year, target_month, target_day, 0, 0, 0, 0, 0)
        )

        days = (target_ts - today_ts) // 86400
        return max(0, days)

    except Exception as e:
        print("get_days error:", e)
        return -1


# ===== HTTP SERVER - HELPING METHODS=====
# PART 1 :
def safe_color(c):
    c = c.replace('%23', '#')
    if c.startswith('#') and len(c) in (4, 7):
        return c
    return 'rgba(0, 31, 77, 0.85)'

def parse_form(body):
    params = {}
    for pair in body.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            v = (
                v.replace("+", " ")
                 .replace("%20", " ")
                 .replace("%23", "#")   # ✅ FIX
            )
            params[k] = v
    return params

def parse_query_string(path):
    params = {}
    if "?" not in path:
        return params

    query = path.split("?", 1)[1]
    for part in query.split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            v = v.replace("+", " ")
            params.setdefault(k, [])
            params[k].append(v)

    # flatten single values
    for k in list(params.keys()):
        if len(params[k]) == 1:
            params[k] = params[k][0]

    return params

def clean_response(html: str) -> str:
    if not html:
        return ""

    # Remove invisible garbage characters
    html = html.strip()

    # Remove accidental trailing < or >
    while html.endswith("<") or html.endswith(">"):
        html = html[:-1].rstrip()

    return html

async def safe_readline(reader):
    try:
        return await reader.readline()
    except:
        return b''

async def read_exact(reader, size):
    data = b""
    while len(data) < size:
        chunk = await reader.read(size - len(data))
        if not chunk:
            break
        data += chunk
    return data

# ===== HTTP SERVER =====
async def handle_client(reader, writer):
    global new_timezone, trigger_on, brightness, time_configured
    try:
        line = await safe_readline(reader)
        if not line:
            return

        parts = line.decode().split()
        if len(parts) < 2:
            await writer.aclose()
            return
        method, path = parts[0], parts[1]

        content_length = 0

        while True:
            hl = await safe_readline(reader)
            if not hl or hl == b"\r\n":
                break
            h = hl.lower()
            # ✅ FIX FOR CHROME (Expect: 100-continue)
            if h.startswith(b"expect:"):
                await writer.awrite(b"HTTP/1.1 100 Continue\r\n\r\n")
                continue
            if h.startswith(b"content-length:"):
                content_length = int(hl.decode().split(":", 1)[1].strip())

        body = ""
        if method == "POST" and content_length > 0:
            raw = await read_exact(reader, content_length)
            body = raw.decode("utf-8") if raw else ""

        response_body = "<h1>404 Not Found</h1>"
        content_type = "text/html"

        if path == "/" and method == "POST":
            try:
                params = parse_form(body)
                h = params["hour"]
                m = params["minute"]

                global time_task, time_status

                # cancel previous attempt
                if time_task and not time_task.done():
                    time_task.cancel()

                print(f"Setting time... | Inserted time : {h}:{m}")
                time_task = asyncio.create_task(set_manual_time(
                    int(params["year"]),
                    int(params["month"]),
                    int(params["day"]),
                    int(h),
                    int(m),
                ))

                # ✅ SEND REDIRECT
                await writer.awrite(
                    b"HTTP/1.1 303 See Other\r\n"
                    b"Location: /time-answer\r\n"
                    b"Content-Length: 0\r\n"
                    b"Connection: close\r\n\r\n"
                )

                await writer.aclose()
                return  # 🚨 MUST RETURN HERE

            except Exception as e:
                response_body = get_html("set-time").replace(
                    "{message}", escape_html(str(e))
                )
        elif path == "/" and not time_configured:
            response_body = get_html('set-time').replace('{message}', '')
        elif path == "/" and time_configured:
            html_template = get_html('home')
            response_body = html_template
        elif path == "/time-answer":
            html = clean_response(get_html('time-answer'))
            if time_status == "set":
                answer = """<h1>✅ Time is set!</h1>
<p>Inserted time was saved 🌍</p>
<a href="/" class="button">🏠 Home</a>"""
                html = html.replace('{answer}', answer)
            elif time_status == "failed":
                answer = """<h1>❌ Couldn't save time.</h1>
<p>Wrong or not logical input.</p>
<a href="/" class="button">⬅ Try Again</a>
"""
                html = html.replace('{answer}', answer)
            else:
                answer = """<h1>⏰ Setting...</h1>
<p>Please wait a few seconds</p>

<script>
setTimeout(() => {
    location.reload();
}, 5000);
</script>
"""
                html = html.replace('{answer}', answer)
            response_body = html
        elif path == "/time":
            html_template = get_html('time')
            h = ''
            m = ''
            if len(str(current_h)) == 1:
                h += '0'
            h += str(current_h)

            if len(str(current_m)) == 1:
                m += '0'
            m += str(current_m)
            time = f'{h}:{m}'

            y, m, d = current_date.split('-')
            date = f'{d}-{m}-{y}'

            response_body = html_template.replace('{time}', time).replace('{date}', date)
        elif path == "/refresh-time":
            refresh_time()
            html_template = get_html('set-time')
            response_body = html_template.replace('{message}', '')
        # ===== IMPORTANT DAYS =====
        elif path == "/important-days":
            items = ""

            for day in daysBase.list_days():
                y, m, d = split_date(current_date)
                print(day.date)
                days_left = get_days(day.date, y, m, d)

                day_color = safe_color(day.color)  # CSS only
                day_decorations = "⭐"
                day_class = "button"

                if days_left == 0:
                    day_decorations = "🎉"
                    day_class += " vibrate pulse today"
                elif days_left == 1:
                    day_decorations = "⏳"
                    day_class += " pulse"
                elif 2 <= days_left <= 3:
                    day_class += " pulse"

                items += (
                    f'<a href="/important-days/{day.id()}" '
                    f'class="{day_class}" '
                    f'style="background: {day_color};">'
                    f'{day_decorations} {escape_html(day.name)}'
                    f'</a>'
                )

            html_template = get_html('important_days')
            response_body = clean_response(html_template.replace('{days}', items))
        elif path == "/add-day":
            html = get_html("add-day")
            response_body = html
        elif path == "/save-day" and method == 'POST':
            try:
                params = parse_form(body)
                print(params)

                # ---- name
                name = params.get("name", "").strip()
                if len(name) < 2:
                    raise ValueError("Name too short")

                # ---- date
                date = params.get("date", "").strip()
                if "-" not in date or len(date.split("-")) != 2:
                    raise ValueError("Invalid date format")

                # ---- color
                color = safe_color(params['color'])

                day = ImportantDay(
                    name=name,
                    date=date,
                    color=color,
                )

                if not daysBase.add_day(day):
                    items = ""

                    for day in daysBase.list_days():
                        y, m, d = split_date(current_date)
                        print(day.date)
                        days_left = get_days(day.date, y, m, d)

                        day_color = safe_color(day.color)  # CSS only
                        day_decorations = "⭐"
                        day_class = "button"

                        if days_left == 0:
                            day_decorations = "🎉"
                            day_class += " vibrate pulse today"
                        elif days_left == 1:
                            day_decorations = "⏳"
                            day_class += " pulse"
                        elif 2 <= days_left <= 3:
                            day_class += " pulse"

                        items += (
                            f'<a href="/important-days/{day.id()}" '
                            f'class="{day_class}" '
                            f'style="background: {day_color};">'
                            f'{day_decorations} {escape_html(day.name)}'
                            f'</a>'
                        )

                    html_template = get_html('important_days')
                    response_body = clean_response(html_template.replace('{days}', items))

                response_body = get_html("day-saved")

            except Exception as e:
                response_body = (
                    "<h1>❌ Error</h1>"
                    f"<p>{escape_html(str(e))}</p>"
                    "<a href='/add-day'>⬅ Back</a>"
                )
        elif path.startswith('/delete-day/'):
            day_id = path.split('/')[-1]
            day = daysBase.get_day(day_id)

            if day:
                daysBase.delete_day(day)

            # reload list
            items = ""
            for day in daysBase.list_days():
                # Calculate days left
                days_left = get_days(day.date,
                                     int(current_date.split('-')[0]),
                                     int(current_date.split('-')[1]),
                                     int(current_date.split('-')[2]))

                # Default
                day_color = day.color
                day_decorations = "⭐"
                day_class = "button"

                # Dynamic styling
                if days_left == 0:
                    day_class += " vibrate pulse today"
                elif days_left == 1:
                    day_class += " pulse"
                elif 2 <= days_left <= 3:
                    day_class += " pulse"

                # Build button
                items += f'<a href="/important-days/{day.id()}" class="{day_class}" style="background: {day_color};">{day_decorations} {escape_html(day.name)}</a>'

            html_template = get_html('important_days')
            response_body = clean_response(html_template.replace('{days}', items))
        elif path.startswith('/important-days/'):
            try:
                day_id = path.split('/')[-1]
                day = daysBase.get_day(day_id)

                if not day:
                    raise Exception("Day not found")

                days, today = days_until(day.date)

                if days == 0:
                    days_left = 'Today 🎉'
                elif days == 1:
                    days_left = 'Tomorrow ⏳'
                else:
                    days_left = f'{days} days ⏳'

                html = get_html('date')

                response_body = clean_response(
                    html
                    .replace('{event_name}', escape_html(day.name))
                    .replace('{event_date}', escape_html(day.date))
                    .replace('{days_left}', escape_html(days_left))
                    .replace('{today}', escape_html(today))
                    .replace('{id}', day.id())  # ID is safe
                    .replace('{card_color}', safe_color(day.color))  # color only
                )

            except Exception as e:
                response_body = (
                    "<h1>Error</h1>"
                    f"<pre>{escape_html(str(e))}</pre>"
                )
        elif path.startswith('/edit-day/'):
            try:
                day_id = path.split('/')[-1]
                day = daysBase.get_day(day_id)

                if not day:
                    raise Exception("Day not found")

                html = get_html('edit-day')
                response_body = (
                    html.replace('{id}', day.id())
                    .replace('{name}', escape_html(day.name))
                    .replace('{date}', day.date)
                    .replace('{color}', day.color)
                )

            except Exception as e:
                response_body = f"<h1>Error</h1><pre>{e}</pre>"
        elif path == '/update-day' and method == 'POST':
            try:
                params = parse_form(body)
                print(params)

                name = params.get("name", "").strip()
                date = params.get("date", "").strip()
                color = params['color']
                id = params.get("id", "").strip()

                day = daysBase.get_day(id)

                if not day:
                    raise Exception("Day not found")

                result = daysBase.edit_day(
                    day,
                    escape_html(name)
                    .replace('%27', "'")
                    .replace('+', ' ')
                    .replace('%2B', '+')
                    .replace('%60', '`')
                    .replace('%E2%80%99', '`')
                    .replace('%C3%B1', 'ñ'),
                    date,
                    color,
                )

                if result:
                    response_body = get_html("day-updated")
                else:
                    raise Exception("Invalid date format")

            except Exception as e:
                response_body = f"<h1>Error</h1><pre>{e}</pre>"

        # ===== ALARMS =====
        elif path == "/alarms":
            items = ""
            for a in alarms_manager.list_alarms():
                state_text = "ON" if a.enabled else "OFF"
                toggle_text = "Turn Off" if a.enabled else "Turn On"
                items += (
                    f"<div style='margin:15px;'>"
                    f"<b>{escape_html(a.name).replace('+', ' ')}</b> – {a.h:02d}:{a.m:02d} - {str(a.repeat).upper()} - {state_text}<br>"
                    f"<a class='button {'off' if toggle_text == 'Turn Off' else 'on'}' href='/toggle-alarm/{a.id()}'>{toggle_text}</a>"
                    f"<a class='button edit' href='/edit-alarm/{a.id()}'>Edit</a>"
                    f"<a class='button delete' href='/delete-alarm/{a.id()}'>Delete</a>"
                    f"</div>"
                )
            if not items:
                items = ""
            html_template = get_html("alarms")
            response_body = html_template.replace("{alarms}", items)
        elif path == "/add-alarm":
            response_body = get_html("add_alarm")
        elif path.startswith("/save-alarm"):
            try:
                # Parse query string
                _, qs = path.split("?", 1)
                params = {}

                for p in qs.split("&"):
                    k, v = p.split("=", 1)
                    params[k] = v.replace("+", " ")

                alarm_name = params.get("name", "Alarm")
                if len(alarm_name) < 3:
                    alarm_name = "Alarm"

                alarm = Alarm(
                    h=int(params["h"]),
                    m=int(params["m"]),
                    name=escape_html(alarm_name),
                    repeat=params.get("repeat", "once"),
                    enabled=True
                )

                alarms_manager.add_alarm(alarm)
                save_data()

                response_body = get_html("alarm_saved")

            except Exception as e:
                response_body = f"<h1>Error</h1><pre>{e}</pre>"
        elif path.startswith("/delete-alarm/"):
            alarm_id = path.split("/")[-1]
            alarms_manager.delete_alarm(alarm_id)
            items = ""
            for a in alarms_manager.list_alarms():
                state_text = "ON" if a.enabled else "OFF"
                toggle_text = "Turn Off" if a.enabled else "Turn On"
                items += (
                    f"<div style='margin:15px;'>"
                    f"<b>{escape_html(a.name).replace('+', ' ')}</b> – {a.h:02d}:{a.m:02d} - {str(a.repeat).upper()} - {state_text}<br>"
                    f"<a class='button {'off' if toggle_text == 'Turn Off' else 'on'}' href='/toggle-alarm/{a.id()}'>{toggle_text}</a>"
                    f"<a class='button edit' href='/edit-alarm/{a.id()}'>Edit</a>"
                    f"<a class='button delete' href='/delete-alarm/{a.id()}'>Delete</a>"
                    f"</div>"
                )
            if not items:
                items = ""
            html_template = get_html("alarms")
            response_body = html_template.replace("{alarms}", items)
        elif path.startswith("/toggle-alarm/"):
            alarm = alarms_manager.get_alarm(path.split("/")[-1])
            if alarm:
                if active_alarm == alarm:
                    trigger_on = False
                alarm.enabled = not alarm.enabled
                save_data()
            items = ""
            for a in alarms_manager.list_alarms():
                state_text = "ON" if a.enabled else "OFF"
                toggle_text = "Turn Off" if a.enabled else "Turn On"
                items += (
                    f"<div style='margin:15px;'>"
                    f"<b>{escape_html(a.name).replace('+', ' ')}</b> – {a.h:02d}:{a.m:02d} - {str(a.repeat).upper()} - {state_text}<br>"
                    f"<a class='button {'off' if toggle_text == 'Turn Off' else 'on'}' href='/toggle-alarm/{a.id()}'>{toggle_text}</a>"
                    f"<a class='button edit' href='/edit-alarm/{a.id()}'>Edit</a>"
                    f"<a class='button delete' href='/delete-alarm/{a.id()}'>Delete</a>"
                    f"</div>"
                )
            if not items:
                items = "<p>No alarms yet</p>"
            html_template = get_html("alarms")
            response_body = html_template.replace("{alarms}", items)
        elif path.startswith("/edit-alarm/"):
            alarm_id = path.split("/")[-1]
            alarm = alarms_manager.get_alarm(str(alarm_id))

            # Alarm NOT found → show alarms page
            if not alarm:
                html_template = get_html("alarms")
                items = ""

                for a in alarms_manager.list_alarms():
                    toggle_text = "Turn Off" if a.enabled else "Turn On"
                    toggle_class = "off" if a.enabled else "on"

                    items += (
                        f"<div style='margin:15px;'>"
                        f"<b>{escape_html(a.name)}</b> – {a.h:02d}:{a.m:02d} - {a.repeat.upper()}<br>"
                        f"<a class='button {toggle_class}' href='/toggle-alarm/{a.id()}'>{toggle_text}</a>"
                        f"<a class='button edit' href='/edit-alarm/{a.id()}'>Edit</a>"
                        f"<a class='button delete' href='/delete-alarm/{a.id()}'>Delete</a>"
                        f"</div>"
                    )

                response_body = html_template.replace("{alarms}", items)

            else:
                html = get_html("edit_alarm")

                repeat_once = "selected" if alarm.repeat == "once" else ""
                repeat_daily = "selected" if alarm.repeat == "daily" else ""

                response_body = (
                    html.replace("{id}", alarm.id())
                    .replace("{name}", escape_html(alarm.name or "Alarm"))
                    .replace("{h}", str(alarm.h))
                    .replace("{m}", str(alarm.m))
                    .replace("{repeat_once}", repeat_once)
                    .replace("{repeat_daily}", repeat_daily)
                )
        elif path.startswith("/update-alarm"):
            try:
                _, qs = path.split("?", 1)
                params = {}

                for p in qs.split("&"):
                    k, v = p.split("=", 1)
                    params[k] = v.replace("+", " ")

                alarm = alarms_manager.get_alarm(params["id"])

                if alarm:
                    alarm.name = escape_html(params.get("name", alarm.name))
                    alarm.h = int(params["h"])
                    alarm.m = int(params["m"])
                    alarm.repeat = params.get("repeat", alarm.repeat)
                    save_data()

                save_data()
                response_body = get_html("alarm_updated")

            except Exception as e:
                response_body = f"<h1>Error</h1><pre>{e}</pre>"

        # ===== DISPLAY =====
        elif path == '/display':
            html = get_html('display')
            response_body = (
                html.replace('{brightness}', str(brightness) if display_on else 'OFF')
                .replace('{message}', '')
            )
        elif path == '/display/on':
            display_power(True)
            display_brightness(brightness)
            html = get_html('display')
            response_body = (
                html.replace('{brightness}', str(brightness))
                .replace('{message}', '')
            )
        elif path == '/display/off':
            display_power(False)
            html = get_html('display')
            response_body = (
                html.replace('{brightness}', 'OFF')
                .replace('{message}', '')
            )
        elif path == '/display/plus':
            result = display_brightness(brightness + 1)
            html = get_html('display')
            response_body = (
                html.replace('{brightness}', str(brightness) if display_on else 'OFF')
                .replace('{message}', result or '')
            )
        elif path == '/display/minus':
            result = display_brightness(brightness - 1)
            html = get_html('display')
            response_body = (
                html.replace('{brightness}', str(brightness) if display_on else 'OFF')
                .replace('{message}', result or '')
            )

        body_bytes = response_body.encode("utf-8")

        headers = (
            "HTTP/1.1 200 OK\r\n"
            f"Content-Type: {content_type}; charset=utf-8\r\n"
            f"Content-Length: {len(body_bytes)}\r\n"
            "Connection: close\r\n\r\n"
        )

        await writer.awrite(headers.encode())
        await writer.awrite(body_bytes)

    except Exception as e:
        print("Server Error:", e)
        try:
            response_body = get_html('home')
            headers = (
                "HTTP/1.1 302 Found\r\n"
                "Location: /\r\n"
                "Connection: close\r\n\r\n"
            )
            await writer.awrite(headers.encode())
        except:
            pass
    finally:
        try:
            await writer.aclose()
        except:
            pass
        gc.collect()

# ===== DISPLAY FUNC =====
async def set_manual_time(y, mo, d, h, m):
    global time_status, time_configured
    try:
        time_status = "connecting"
        time_configured = False
        asyncio.sleep_ms(100)
        global base_epoch, base_ticks, current_date
        base_epoch = utime.mktime((y, mo, d, h, m, 0, 0, 0))
        base_ticks = utime.ticks_ms()
        current_date = f"{y:04d}-{mo:02d}-{d:02d}"
        asyncio.sleep_ms(200)
        time_status = 'set'
        time_configured = True
        print(f'Time was set ! Current date : {current_date}')
    except Exception as e:
        time_status = 'failed'
        time_configured = False
        print(f'Setting time failed ! ERROR : {e}')

async def display_time_loop():
    global current_h, current_m, current_date

    while True:
        elapsed = utime.ticks_diff(utime.ticks_ms(), base_ticks)
        now = base_epoch + elapsed // 1000

        y, month, d, h, m, _, _, _ = utime.localtime(now)
        current_h = h
        current_m = m
        current_date = f"{y}-{month:02d}-{d:02d}"

        if display_on:
            if time_configured:
                display.number(h * 100 + m, colon=True)
            else:
                display.show('----', colon=False)

        await asyncio.sleep_ms(200)

# ===== DISPLAY CONFIGURATIONS =====
def display_brightness(value):
    global brightness, display_on

    if not display_on:
        return "Display is OFF"

    if value < 0:
        brightness = 0
        display.brightness = brightness
        return "Minimum brightness reached"

    if value > 3:
        brightness = 3
        display.brightness = brightness
        return "Maximum brightness reached"

    brightness = value
    display.brightness = brightness
    return None

def display_power(on):
    global display_on
    display_on = on
    if display_on:
        display.power_on()
    else:
        display.power_off()

async def display_switch():
    global display_on
    print('Display Switch activated.')
    while True:
        if not display_button.value():
            if display_on:
                print('Display to OFF')
                display_power(False)
            else:
                print('Display to ON')
                display_power(True)
        await asyncio.sleep(1)

# ===== RUN SERVER =====
async def main():
    await asyncio.sleep(1)   # ⏳ let event loop settle

    print("📡 Starting AP...")
    start_ap()

    await asyncio.sleep(1)

    print("📂 Loading data...")
    load_data()

    asyncio.create_task(display_time_loop())
    await asyncio.sleep(0.5)

    asyncio.create_task(alarms_manager.run())
    await asyncio.sleep(0.5)

    asyncio.create_task(display_switch())
    await asyncio.sleep(0.5)

    await asyncio.start_server(handle_client, "0.0.0.0", 80)
    print("🌍 Server running on port 80")

    while True:
        await asyncio.sleep(5)

asyncio.run(main())