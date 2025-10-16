import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
import tensorflow as tf
from sklearn.preprocessing import StandardScaler
import numpy as np
from datetime import datetime
import pytz

# =========================================
# ✅ SECURE FIREBASE INITIALIZATION
# =========================================
firebase_key_json = os.environ.get("FIREBASE_KEY")

if not firebase_key_json:
    raise ValueError("❌ FIREBASE_KEY environment variable not set. Please configure it in Render or GitHub Secrets.")

firebase_key = json.loads(firebase_key_json)

cred = credentials.Certificate(firebase_key)
firebase_admin.initialize_app(cred)
db = firestore.client()

# =========================================
# ✅ LOAD TRAINED MODEL
# =========================================
model = tf.keras.models.load_model("yield_model.keras")

# =========================================
# ✅ GET CURRENT PHILIPPINE TIME
# =========================================
ph_tz = pytz.timezone("Asia/Manila")
now = datetime.now(ph_tz)
formatted_date = now.strftime("%m/%d/%Y")
formatted_year = now.strftime("%Y")
formatted_month = now.strftime("%Y-%m")
formatted_train_time = now.strftime("%Y-%m-%d %I:%M %p")
formatted_time_only = now.strftime("%I:%M %p")

# =========================================
# ✅ FETCH ONLY TODAY’S DATA
# =========================================
docs = (
    db.collection("dataCollectionSensor")
    .where("date", "==", formatted_date)
    .order_by("timestamp", direction=firestore.Query.DESCENDING)
    .stream()
)

trained_at = datetime.now(ph_tz).strftime("%Y-%m-%d %I:%M %p")

db.collection("trainingLogs").add({
    "trained_at": trained_at,
    "note": "Auto-retrain schedule",
})

unlabeled_data = []
docs_to_update = []

for doc in docs:
    record = doc.to_dict()

    if all(k in record for k in ["temperature", "humidity", "localMoisture"]):
        unlabeled_data.append([
            int(record["temperature"]),
            int(record["humidity"]),
            int(record["localMoisture"])
        ])
        docs_to_update.append((doc.id, record))

if not unlabeled_data:
    print("No new sensor data to predict.")
    exit()

# =========================================
# ✅ SCALE & PREDICT
# =========================================
scaler = StandardScaler()
X_scaled = scaler.fit_transform(unlabeled_data)
predicted_yields = model.predict(X_scaled).flatten()

# =========================================
# ✅ DETERMINE MAX INDEX SO FAR FOR TODAY
# =========================================
existing = db.collection("predictedYield").where("date", "==", formatted_date).stream()
existing_indices = [int(doc.to_dict().get("index", 0)) for doc in existing]
index_counter = max(existing_indices, default=-1) + 1

# =========================================
# ✅ SAVE PREDICTIONS & ACCUMULATE TOTAL
# =========================================
total_day_yield = 0

for i, (doc_id, original) in enumerate(docs_to_update):
    timestamp = datetime.now(ph_tz)
    formatted_time = timestamp.strftime("%I:%M %p")
    hour_only = timestamp.strftime("%I")
    day_only = str(timestamp.day)

    predicted = float(predicted_yields[i])
    total_day_yield += predicted

    db.collection("predictedYield").add({
        "temperature": original["temperature"],
        "humidity": original["humidity"],
        "soilMoisture": original["localMoisture"],
        "timestamp": timestamp.isoformat(),
        "date": formatted_date,
        "time": formatted_time,
        "day": day_only,
        "hour": hour_only,
        "index": str(index_counter),
        "predicted_yield": round(predicted, 2),
        "source": "predicted",
        "trained_at": formatted_train_time
    })

    index_counter += 1

# =========================================
# ✅ SAVE TO DAILY READING
# =========================================
db.collection("DailyReading").add({
    "date": formatted_date,
    "total_yield": round(total_day_yield, 2),
    "trained_at": formatted_train_time
})

# =========================================
# ✅ UPDATE MONTHLY SUMMARY
# =========================================
timestamp_str = record.get("timestamp")
year = None

if timestamp_str:
    try:
        year = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S").year
    except ValueError:
        print("⚠️ Invalid timestamp format")

first_of_month = formatted_month

try:
    monthly_docs = db.collection("monthlyYieldSummary").where("month", "==", first_of_month).get()

    if monthly_docs:
        print("🔄 Updating monthly total...")
        monthly_doc = monthly_docs[0]
        doc_ref = monthly_doc.reference
        prev_total = monthly_doc.to_dict().get("total_yield", 0)
        new_total = prev_total + total_day_yield

        doc_ref.update({
            "total_yield": round(new_total, 2),
            "past_updated": formatted_train_time,
            "formatTimeUpdate": formatted_time_only,
            "year": year or int(formatted_year)
        })
    else:
        print("🆕 Creating new month summary...")
        db.collection("monthlyYieldSummary").add({
            "month": first_of_month,
            "total_yield": round(total_day_yield, 2),
            "past_updated": formatted_train_time,
            "formatTimeUpdate": formatted_time_only,
            "year": year or int(formatted_year)
        })

except Exception as e:
    print(f"⚠️ Failed to update monthly total: {e}")

# =========================================
# ✅ FINAL LOGS
# =========================================
print(f"✅ {len(predicted_yields)} predictions saved.")
print(f"📊 Total predicted yield for {formatted_date}: {round(total_day_yield, 2)}")
print(f"📆 Monthly yield summary for {formatted_month} updated successfully.")
