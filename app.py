from flask import Flask, render_template, Response, request, redirect
import cv2
import random
import threading
import time
import sqlite3
from twilio.rest import Client
import os
from flask import jsonify
from ultralytics import YOLO

app = Flask(__name__)
model=YOLO("yolov8n.pt")

# =========================================================
#  TWILIO CONFIG — PUT YOUR DETAILS
# =========================================================

ACCOUNT_SID = ""
AUTH_TOKEN = ""
TWILIO_PHONE = "+"   # Twilio number
USER_PHONE = "+91"    # Your mobile number

client = Client(ACCOUNT_SID, AUTH_TOKEN)

# =========================================================
#  GLOBAL VARIABLES
# =========================================================
THRESHOLD = 80
monitoring = False
people_count = 0
alert_sent=False
video_source=0
current_people=0
alert_threshold=15
authority_phone="+91"
last_sms_time=0
sms_cooldown=30

# =========================================================
#  SEND SMS FUNCTION
# =========================================================

def send_sms(phone,count):
    print("SMS FUNCTION RUNNING")
    global alert_sent

    try:
        message = client.messages.create(
            body=f" Railway Alert: High crowd detected! Count = {count}",
            from_=TWILIO_PHONE,
            to=phone
        )
        alert_sent=True
        print("SMS SENT:", message.sid)

    except Exception as e:
        print("SMS ERROR:", e)

# =========================================================
#  DATABASE FUNCTIONS
# =========================================================

def init_db():
    conn = sqlite3.connect("settings.db")
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            threshold INTEGER,
            phone TEXT,
            station TEXT,
            area TEXT,
            sms TEXT,
            sensitivity TEXT
        )
    """)

    conn.commit()
    conn.close()

def get_settings():
    conn = sqlite3.connect("settings.db")
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM settings ORDER BY id DESC LIMIT 1")
    data = cursor.fetchone()

    conn.close()

    return data

# =========================================================
#  VIDEO STREAM FUNCTION
# =========================================================
def process_video():
    
    global video_source, monitoring, current_people

    cap = cv2.VideoCapture(video_source)

    while True:

        success, frame = cap.read()

        if not success:
            break

        people_count = 0

        # Run YOLO only when monitoring is active
        if monitoring:

            results = model(frame)

            for r in results:
                for box in r.boxes:

                    cls = int(box.cls[0])

                    # 0 = person class in COCO dataset
                    if cls == 0:

                        people_count += 1

                        x1, y1, x2, y2 = map(int, box.xyxy[0])

                        # Draw green rectangle
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0,255,0), 2)

                        # Label
                        cv2.putText(frame,
                                    "Person",
                                    (x1, y1-10),
                                    cv2.FONT_HERSHEY_SIMPLEX,
                                    0.6,
                                    (0,255,0),
                                    2)

        # Update global people count
        current_people = people_count

        # Display total count on frame
        cv2.putText(frame,
                    f"People: {people_count}",
                    (20,40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1,
                    (0,255,0),
                    3)

        ret, buffer = cv2.imencode('.jpg', frame)

        frame = buffer.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        time.sleep(0.03)
# =========================================================
#  ROUTES
# =========================================================

sms_sent=False
@app.route("/")
def home():
    return render_template("login.html")

@app.route("/login", methods=["GET","POST"])
def login():

    if request.method == "POST":
            return redirect("/camera")   # 👈 IMPORTANT

    return render_template("login.html")


@app.route("/camera", methods=["GET", "POST"])
def camera():

    if request.method == "POST":

        if "video" not in request.files:
            return "No file uploaded"

        file = request.files["video"]

        if file.filename == "":
            return "No selected file"

        filepath = os.path.join("static/uploads", file.filename)
        file.save(filepath)

        # Save uploaded file path globally
        global video_source
        video_source = filepath

        return redirect("/dashboard")

    return render_template("camera.html")

@app.route("/dashboard")
def dashboard():
    global current_people

    # Read threshold from settings database
    conn = sqlite3.connect("settings.db")
    cursor = conn.cursor()

    cursor.execute("SELECT threshold, station, area FROM settings LIMIT 1")
    data = cursor.fetchone()

    conn.close()

    if data:
        alert_threshold = data[0]
        station = data[1]
        area = data[2]
    else:
        alert_threshold = 10
        station = "Central Railway Station"
        area = "Platform 1"

    # Determine risk level
    if current_people > alert_threshold:
        risk = "HIGH"
    else:
        risk = "NORMAL"

    return render_template(
        "dashboard.html",
        people_count=current_people,
        risk=risk,
        station=station,
        area=area
    )

@app.route("/alerts")
def alerts():

    global alert_sent, current_people

    conn = sqlite3.connect("settings.db")
    cursor = conn.cursor()

    cursor.execute("SELECT threshold FROM settings LIMIT 1")
    row = cursor.fetchone()

    alert_threshold = row[0] if row else 10

    conn.close()

    if current_people > alert_threshold:
        print("Alert Triggered")
        status = "HIGH"
        message="Crowd Alert"
        action="Authority Notified"
        alert = True
        color="red"

        if not alert_sent:
            send_sms("+919182758423",current_people)
            alert_sent=True


    else:
        status = "NORMAL"
        message="Situation Under Control"
        action="Monitoring"
        alert = False
        color="green"

        alert_sent=False

    return render_template("alerts.html",
                           people_count=current_people,
                           status=status,
                           message=message,
                           action=action,
                           alert=alert,
                           color=color)

                           
@app.route("/settings")
def settings():

    conn = sqlite3.connect("settings.db")
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM settings ORDER BY id DESC LIMIT 1")
    data = cursor.fetchone()

    conn.close()

    return render_template("settings.html", data=data)

@app.route("/video")
def video():
    return Response(process_video(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route("/analytics")
def analytics():
    return render_template("analytics.html")
# =========================================================
# ▶ START / STOP CONTROLS
# =========================================================

@app.route("/start")
def start():
    global monitoring
    monitoring = True
    return redirect("/dashboard")

@app.route("/stop")
def stop():
    global monitoring
    monitoring = False
    return redirect("/dashboard")

@app.route("/manual_alert")
def manual_alert():
    send_sms(authority_phone,current_people)
    return redirect("/alerts")

@app.route("/announce")
def announce():
    return redirect("/dashboard")

@app.route("/system_check")
def system_check():
    return "System functioning normally"

@app.route("/live_data")
def live_data():

    global current_people,last_sms_time

    conn = sqlite3.connect("settings.db")
    cursor = conn.cursor()

    cursor.execute("SELECT threshold FROM settings ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()

    alert_threshold = int(row[0]) if row else 10

    conn.close()

    print("People:", current_people)
    print("Threshold:", alert_threshold)

    current_time=time.time()


    if current_people > alert_threshold:
        status = "HIGH"
        alert = True

        print("ALERT TRIGGERED")
        if current_time-last_sms_time>sms_cooldown:
            send_sms(authority_phone,current_people)
        last_sms_time=current_time



    else:
        status = "NORMAL"
        alert = False

    return jsonify({
        "people": current_people,
        "status": status,
        "alert": alert,
        "threshold": alert_threshold,
    })
#=========================================================
#  SAVE SETTINGS
# =========================================================

@app.route("/save_settings", methods=["POST"])
def save_settings():

    threshold = request.form["threshold"]
    phone = request.form["phone"]
    station = request.form["station"]
    area = request.form["area"]
    sms = request.form["sms"]
    sensitivity = request.form["sensitivity"]

    conn = sqlite3.connect("settings.db")
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO settings
        (threshold, phone, station, area, sms, sensitivity)
        VALUES (?, ?, ?, ?, ?, ?)
    """,(threshold,phone,station,area,sms,sensitivity))

    conn.commit()
    conn.close()

    return redirect("/settings?success=1")
# =========================================================
#  RUN APP
# =========================================================

if __name__ == "__main__":
    init_db()
    video_thread = threading.Thread(target=process_video)
    video_thread.daemon = True
    video_thread.start()

    app.run(debug=True, threaded=True)
