from flask import Flask, request, jsonify, render_template_string
import sqlite3, datetime, re
from dateutil import parser as dateparser

app = Flask(__name__)

CLIENTS = {
    "srirenuka": {"name": "Sri Renuka Dental", "color": "#2563eb"},
    "abhi": {"name": "Abhi Dental Clinic", "color": "#dc2626"},
    "demo": {"name": "Demo Clinic", "color": "#2563eb"}
}

def init_db():
    conn = sqlite3.connect('leads.db')
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS sessions
                 (phone TEXT, client_id TEXT, stage TEXT, service TEXT,
                  appointment_time TEXT, name TEXT, updated_at TEXT, PRIMARY KEY (phone, client_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS leads
                 (id INTEGER PRIMARY KEY, client_id TEXT, phone TEXT, name TEXT,
                  service TEXT, appointment_time TEXT, created_at TEXT, status TEXT)""")
    conn.commit()
    conn.close()

init_db()

def get_session(phone, client_id):
    conn = sqlite3.connect('leads.db')
    c = conn.cursor()
    c.execute("SELECT * FROM sessions WHERE phone=? AND client_id=?", (phone, client_id))
    row = c.fetchone()
    conn.close()
    if row:
        return {"phone":row[0],"client_id":row[1],"stage":row[2],"service":row[3],"appointment_time":row[4],"name":row[5]}
    return {"phone":phone,"client_id":client_id,"stage":"start","service":None,"appointment_time":None,"name":None}

def update_session(phone, client_id, **kwargs):
    conn = sqlite3.connect('leads.db')
    c = conn.cursor()
    sess = get_session(phone, client_id)
    sess.update(kwargs)
    sess['updated_at'] = datetime.datetime.now().isoformat()
    c.execute("""INSERT OR REPLACE INTO sessions (phone,client_id,stage,service,appointment_time,name,updated_at)
                 VALUES (?,?,?,?,?,?,?)""", (sess['phone'],sess['client_id'],sess['stage'],sess['service'],sess['appointment_time'],sess['name'],sess['updated_at']))
    conn.commit()
    conn.close()

def save_lead(client_id, phone, name, service, appointment_time):
    conn = sqlite3.connect('leads.db')
    c = conn.cursor()
    c.execute("""INSERT INTO leads (client_id,phone,name,service,appointment_time,created_at,status)
                 VALUES (?,?,?,?,?,?,?)""", (client_id,phone,name,service,appointment_time,datetime.datetime.now().isoformat(),"booked"))
    conn.commit()
    conn.close()

def parse_date(text):
    text = text.lower().replace('tommorrow','tomorrow')
    try:
        if 'tomorrow' in text:
            dt = datetime.datetime.now() + datetime.timedelta(days=1)
        elif 'today' in text:
            dt = datetime.datetime.now()
        else:
            dt = dateparser.parse(text, fuzzy=True, dayfirst=True)

        # Extract time if present
        time_match = re.search(r'(\d{1,2})\s*(am|pm)', text)
        if time_match:
            hour = int(time_match.group(1))
            if time_match.group(2) == 'pm' and hour!= 12: hour += 12
            if time_match.group(2) == 'am' and hour == 12: hour = 0
            dt = dt.replace(hour=hour, minute=0)
        else:
            dt = dt.replace(hour=17, minute=0) # default 5pm

        return dt.strftime('%d-%m-%Y %I:%M %p')
    except:
        return None

def process_message(message, phone, client_id):
    msg = message.lower().strip()
    sess = get_session(phone, client_id)
    stage = sess['stage']

    # Stage 1: Start
    if stage == 'start' or any(x in msg for x in ['hi','hello','hey','start']):
        update_session(phone, client_id, stage='service')
        return "Hi! 👋 What service do you need?\n\n1 - Cleaning\n2 - Implant\n3 - Checkup\n\nJust reply with number or name."

    # Stage 2: Service selection
    if stage == 'service':
        if '1' in msg or 'clean' in msg:
            update_session(phone, client_id, stage='datetime', service='Cleaning')
            return "Cleaning selected ✅\n\nWhen works for you? Examples:\ntomorrow 5pm\n21-05-2026 3pm\ntoday 11am"
        elif '2' in msg or 'implant' in msg:
            update_session(phone, client_id, stage='datetime', service='Implant')
            return "Implant selected ✅\n\nWhen works for you? Examples:\ntomorrow 5pm\n21-05-2026 3pm"
        elif '3' in msg or 'check' in msg:
            update_session(phone, client_id, stage='datetime', service='Checkup')
            return "Checkup selected ✅\n\nWhen works for you? Examples:\ntomorrow 5pm\n21-05-2026 3pm"
        else:
            return "I didn't catch that. Please reply:\n1 - Cleaning\n2 - Implant\n3 - Checkup"

    # Stage 3: DateTime
    if stage == 'datetime':
        parsed = parse_date(msg)
        if parsed:
            update_session(phone, client_id, stage='name', appointment_time=parsed)
            return f"Got it: {parsed} ✅\n\nWhat's your name for booking?"
        else:
            return "Couldn't understand date. Try:\n• tomorrow 5pm\n• 21-05-2026 3pm\n• today 11am"

    # Stage 4: Name
    if stage == 'name':
        name = message.strip().title()
        if len(name) < 2:
            return "Please enter your full name"
        save_lead(client_id, phone, name, sess['service'], sess['appointment_time'])
        update_session(phone, client_id, stage='done', name=name)
        return f"Perfect {name}! ✅\n\nBooked: {sess['service']} on {sess['appointment_time']}\n\nWe'll confirm on WhatsApp. Type 'hi' to book another."

    # Stage 5: Done
    if stage == 'done':
        update_session(phone, client_id, stage='start')
        return process_message(message, phone, client_id)

    return "Type 'hi' to start booking"

HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{client_name}}</title><style>*{margin:0;padding:0;box-sizing:border-box;font-family:sans-serif}
body{background:#f8fafc}.header{background:{{color}};color:white;padding:20px;text-align:center}
.hero{padding:40px 20px;text-align:center}.btn{background:{{color}};color:white;padding:12px 24px;border:none;border-radius:8px;cursor:pointer}
.chat-toggle{position:fixed;bottom:20px;right:20px;width:60px;height:60px;background:{{color}};border-radius:50%;display:flex;align-items:center;justify-content:center;color:white;font-size:24px;cursor:pointer;z-index:999}
.chat-widget{position:fixed;bottom:20px;right:20px;width:350px;height:500px;background:white;border-radius:12px;box-shadow:0 10px 40px rgba(0,0,0,0.2);display:none;flex-direction:column;z-index:1000}
.chat-header{background:{{color}};color:white;padding:12px;border-radius:12px 12px 0 0}
.chat-messages{flex:1;padding:10px;overflow-y:auto;white-space:pre-wrap}.message{margin:8px 0;padding:8px 12px;border-radius:10px;max-width:80%;font-size:14px}
.bot{background:#e0e7ff}.user{background:{{color}};color:white;margin-left:auto}
.chat-input{display:flex;padding:10px;border-top:1px solid #e2e8f0}
.chat-input input{flex:1;padding:8px;border:1px solid #ccc;border-radius:4px}
.chat-input button{margin-left:5px;padding:8px 12px;background:{{color}};color:white;border:none;border-radius:4px;cursor:pointer}
</style></head><body>
<div class="header"><h2>{{client_name}}</h2><p>AI Receptionist - Online 24/7</p></div>
<div class="hero"><h1>Book Instantly</h1><button class="btn" onclick="toggleChat()">Start Chat</button></div>
<div class="chat-toggle" onclick="toggleChat()">💬</div>
<div class="chat-widget" id="chat"><div class="chat-header">{{client_name}}<span style="float:right;cursor:pointer" onclick="toggleChat()">✕</span></div>
<div class="chat-messages" id="msgs"><div class="message bot">Hi! Type 'hi' to start</div></div>
<div class="chat-input"><input id="inp" placeholder="Type..." onkeypress="if(event.key==='Enter')send()"><button onclick="send()">Send</button></div></div>
<script>
const clientId="{{client_id}}";const phone='91'+Math.floor(Math.random()*9000000000+1000000000);
function toggleChat(){const c=document.getElementById('chat');c.style.display=c.style.display==='flex'?'none':'flex'}
async function send(){const i=document.getElementById('inp');const t=i.value;if(!t)return;add(t,'user');i.value='';
const r=await fetch('/api/chat?c='+clientId,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:t,phone})});
const d=await r.json();add(d.reply,'bot')}
function add(t,c){const d=document.createElement('div');d.className='message '+c;d.textContent=t;document.getElementById('msgs').appendChild(d);document.getElementById('msgs').scrollTop=9999}
</script></body></html>"""

@app.route('/')
def home():
    client_id = request.args.get('c', 'demo')
    client = CLIENTS.get(client_id, CLIENTS['demo'])
    return render_template_string(HTML, client_id=client_id, client_name=client['name'], color=client['color'])

@app.route('/api/chat', methods=['POST'])
def chat():
    client_id = request.args.get('c', 'demo')
    data = request.json
    reply = process_message(data.get('message',''), data.get('phone',''), client_id)
    return jsonify({"reply": reply})

@app.route('/admin')
def admin():
    client_id = request.args.get('c', 'demo')
    conn = sqlite3.connect('leads.db')
    leads = conn.execute("SELECT * FROM leads WHERE client_id=? ORDER BY id DESC", (client_id,)).fetchall()
    conn.close()
    html = f"<h2>{CLIENTS.get(client_id,{}).get('name')} - Bookings ({len(leads)})</h2><table border=1 cellpadding=8><tr><th>Name</th><th>Phone</th><th>Service</th><th>Time</th><th>Status</th></tr>"
    for l in leads: html += f"<tr><td>{l[3]}</td><td>{l[2]}</td><td>{l[4]}</td><td>{l[5]}</td><td>{l[7]}</td></tr>"
    return html + "</table>"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT',5000)))
