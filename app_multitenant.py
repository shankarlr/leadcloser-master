
from flask import Flask, request, jsonify, render_template_string, send_file
import sqlite3, datetime, csv, io, os

app = Flask(__name__)

# CLIENT CONFIG - add new clients here
CLIENTS = {
    "srirenuka": {"name": "Sri Renuka Dental", "color": "#2563eb", "phone": "919000000001"},
    "abhi": {"name": "Abhi Dental Clinic", "color": "#dc2626", "phone": "919000000002"},
    "maya": {"name": "Maya Dental Care", "color": "#059669", "phone": "919000000003"},
    "demo": {"name": "Demo Clinic", "color": "#2563eb", "phone": "919000000000"}
}

def init_db():
    conn = sqlite3.connect('leads_multitenant.db')
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS leads
                 (id INTEGER PRIMARY KEY, client_id TEXT, name TEXT, phone TEXT, 
                  service TEXT, message TEXT, created_at TEXT, booked_at TEXT, status TEXT)""")
    conn.commit()
    conn.close()

init_db()

HTML_TEMPLATE = """
<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{client_name}} - AI Assistant</title>
<style>*{margin:0;padding:0;box-sizing:border-box;font-family:sans-serif}
body{background:#f8fafc}.header{background:{{color}};color:white;padding:20px;text-align:center}
.hero{padding:40px 20px;text-align:center;max-width:600px;margin:0 auto}
.btn{background:{{color}};color:white;padding:12px 24px;border:none;border-radius:8px;cursor:pointer;font-size:16px}
.chat-toggle{position:fixed;bottom:20px;right:20px;width:60px;height:60px;background:{{color}};border-radius:50%;display:flex;align-items:center;justify-content:center;color:white;font-size:24px;cursor:pointer;z-index:999}
.chat-widget{position:fixed;bottom:20px;right:20px;width:350px;height:450px;background:white;border-radius:12px;box-shadow:0 10px 40px rgba(0,0,0,0.2);display:none;flex-direction:column;z-index:1000}
.chat-header{background:{{color}};color:white;padding:12px;border-radius:12px 12px 0 0}
.chat-messages{flex:1;padding:10px;overflow-y:auto}.message{margin:8px 0;padding:8px 12px;border-radius:10px;max-width:80%;font-size:14px}
.bot{background:#e0e7ff}.user{background:{{color}};color:white;margin-left:auto}
.chat-input{display:flex;padding:10px;border-top:1px solid #e2e8f0}
.chat-input input{flex:1;padding:8px;border:1px solid #ccc;border-radius:4px}
.chat-input button{margin-left:5px;padding:8px 12px;background:{{color}};color:white;border:none;border-radius:4px;cursor:pointer}
</style></head><body>
<div class="header"><h2>{{client_name}}</h2><p>AI Receptionist - Replies in 1 second</p></div>
<div class="hero"><h1>Book Your Appointment 24/7</h1><p>Chat below for instant booking</p><button class="btn" onclick="toggleChat()">Start Chat</button></div>
<div class="chat-toggle" onclick="toggleChat()">💬</div>
<div class="chat-widget" id="chat"><div class="chat-header">{{client_name}} - Online <span style="float:right;cursor:pointer" onclick="toggleChat()">✕</span></div>
<div class="chat-messages" id="msgs"><div class="message bot">Hi! I'm the AI assistant for {{client_name}}. What service do you need?</div></div>
<div class="chat-input"><input id="inp" placeholder="Type..." onkeypress="if(event.key==='Enter')send()"><button onclick="send()">Send</button></div></div>
<script>
const clientId = "{{client_id}}"; const phone = '91'+Math.floor(Math.random()*9000000000+1000000000);
function toggleChat(){const c=document.getElementById('chat');c.style.display=c.style.display==='flex'?'none':'flex'}
async function send(){const i=document.getElementById('inp');const t=i.value;if(!t)return;add(t,'user');i.value='';
const r=await fetch('/api/chat?c='+clientId,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:t,phone})});
const d=await r.json();setTimeout(()=>add(d.reply,'bot'),300)}
function add(t,c){const d=document.createElement('div');d.className='message '+c;d.textContent=t;document.getElementById('msgs').appendChild(d);document.getElementById('msgs').scrollTop=9999}
</script></body></html>
"""

@app.route('/')
def home():
    client_id = request.args.get('c', 'demo')
    client = CLIENTS.get(client_id, CLIENTS['demo'])
    return render_template_string(HTML_TEMPLATE, client_id=client_id, client_name=client['name'], color=client['color'])

@app.route('/api/chat')
def chat_api():
    # Actually POST but handle both
    return chat_post()

@app.route('/api/chat', methods=['POST'])
def chat_post():
    client_id = request.args.get('c', 'demo')
    data = request.json
    msg = data.get('message','').lower()
    phone = data.get('phone','')

    if any(x in msg for x in ['hi','hello']):
        reply = "Great! Which service? 1-Cleaning, 2-Implant, 3-Checkup"
    elif '1' in msg or 'clean' in msg:
        reply = "Cleaning selected. When? Reply 'tomorrow 5pm'"
        save_lead(client_id, phone, "Cleaning", msg, "qualified")
    elif '2' in msg or 'implant' in msg:
        reply = "Implant selected. When? Reply 'tomorrow 5pm'"
        save_lead(client_id, phone, "Implant", msg, "qualified")
    elif any(x in msg for x in ['tomorrow','today','pm','am']):
        reply = "✅ Booked! We'll confirm shortly. Your name?"
        save_lead(client_id, phone, "", msg, "booked")
    else:
        reply = "Please choose: 1-Cleaning, 2-Implant, 3-Checkup"
        save_lead(client_id, phone, "", msg, "new")

    return jsonify({"reply": reply})

def save_lead(client_id, phone, service, message, status):
    conn = sqlite3.connect('leads_multitenant.db')
    c = conn.cursor()
    c.execute("INSERT INTO leads (client_id, phone, service, message, created_at, status) VALUES (?,?,?,?,?,?)",
              (client_id, phone, service, message, datetime.datetime.now().isoformat(), status))
    conn.commit()
    conn.close()

@app.route('/admin')
def admin():
    client_id = request.args.get('c', 'demo')
    conn = sqlite3.connect('leads_multitenant.db')
    leads = conn.execute("SELECT * FROM leads WHERE client_id=? ORDER BY id DESC", (client_id,)).fetchall()
    conn.close()
    html = f"<h2>{CLIENTS.get(client_id,{}).get('name')} - Leads ({len(leads)})</h2><table border=1 cellpadding=8><tr><th>Time</th><th>Phone</th><th>Service</th><th>Status</th></tr>"
    for l in leads:
        html += f"<tr><td>{l[6][:16]}</td><td>{l[3]}</td><td>{l[4]}</td><td>{l[8]}</td></tr>"
    html += "</table>"
    return html

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT',5000)))
