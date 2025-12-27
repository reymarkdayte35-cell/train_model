import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
import tensorflow as tf
from sklearn.preprocessing import StandardScaler
import numpy as np
from datetime import datetime, timezone
import pytz

# =========================================
# ✅ SECURE FIREBASE INITIALIZATION (GITHUB ACTIONS)
# =========================================
if "FIREBASE_KEY" not in os.environ:
    raise ValueError("❌ FIREBASE_KEY environment variable not set in GitHub Secrets")

# Load JSON from environment variable (string → dict)
firebase_key = json.loads(os.environ["FIREBASE_KEY"])

# Initialize Firebase app
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

# ISO format date/time for Firestore Timestamp compatibility
today_iso = now.date().isoformat()  # YYYY-MM-DD
formatted_train_time = now.strftime("%Y-%m-%d %I:%M %p")
formatted_time_only = now.strftime("%I:%M %p")
formatted_year = str(now.year)
formatted_month = now.strftime("%Y-%m")  # YYYY-MM

# =========================================
# ✅ FETCH TODAY’S SENSOR DATA
# =========================================
docs = (
    db.collection("dataCollectionSensor")
    .where("date", "==", today_iso)
    .order_by("timestamp", direction=firestore.Query.DESCENDING)
    .stream()
)

# Log training run
db.collection("trainingLogs").add({
    "trained_at": formatted_train_time,
    "note": "Auto-retrain schedule"
})

# =========================================
# ✅ PREPARE DATA FOR PREDICTION
# =========================================
unlabeled_data = []
docs_to_update = []

for doc in docs:
    record = doc.to_dict()
    if all(k in record for k in ["temperature", "humidity", "avgSoilMoisture"]):
        try:
            unlabeled_data.append([
                float(record["temperature"]),
                float(record["humidity"]),
                float(record["avgSoilMoisture"])
            ])
            docs_to_update.append((doc.id, record))
        except Exception:
            continue  # skip malformed rows

if not unlabeled_data:
    print("No new sensor data to predict.")
    raise SystemExit(0)

# Scale and predict
scaler = StandardScaler()
X_scaled = scaler.fit_transform(np.array(unlabeled_data, dtype=float))
predicted_yields = model.predict(X_scaled).flatten()

# Compute total yield for the day
total_day_yield = float(np.sum(predicted_yields))

# =========================================
# ✅ DETERMINE INDEX COUNTER
# =========================================
existing = db.collection("predictedYield").where("date", "==", today_iso).stream()
existing_indices = []

for d in existing:
    idx = d.to_dict().get("index")
    try:
        existing_indices.append(int(idx))
    except Exception:
        continue

index_counter = max(existing_indices, default=-1) + 1

# =========================================
# ✅ SAVE PER-READING PREDICTIONS
# =========================================
for i, (doc_id, original) in enumerate(docs_to_update):
    timestamp = datetime.now(ph_tz)
    formatted_time = timestamp.strftime("%I:%M %p")
    day_only = str(timestamp.day)
    hour_only = str(timestamp.hour)

    predicted = float(predicted_yields[i])

    # Save predictedYield
    db.collection("predictedYield").add({
        "temperature": str(original.get("temperature")),
        "humidity": str(original.get("humidity")),
        "avgSoilMoisture": str(original.get("avgSoilMoisture")),
        "timestamp": timestamp,  # store as Firestore Timestamp
        "date": today_iso,
        "time": formatted_time,
        "day": day_only,
        "hour": hour_only,
        "index": str(index_counter),
        "predicted_yield": str(round(predicted, 2)),
        "source": "predicted",
        "trained_at": formatted_train_time
    })

    index_counter += 1

    # Flag source row as predicted
    try:
        db.collection("dataCollectionSensor").document(doc_id).update({
            "predicted": "True",
            "predicted_at": timestamp,
            "predicted_value": str(round(predicted, 4))
        })
    except Exception as e:
        print(f"[warn] failed to flag source doc {doc_id} as predicted: {e}")

# =========================================
# ✅ SAVE DAILY READING
# =========================================
db.collection("DailyReading").add({
    "date": today_iso,
    "total_yield": str(round(total_day_yield, 2)),
    "trained_at": formatted_train_time
})

# =========================================
# ✅ UPDATE MONTHLY TOTAL
# =========================================
first_of_month = formatted_month  # YYYY-MM
monthly_docs = db.collection("monthlyYieldSummary").where("month", "==", first_of_month).get()

if monthly_docs:
    monthly_doc = monthly_docs[0]
    doc_ref = monthly_doc.reference
    prev_total_raw = monthly_doc.to_dict().get("total_yield", "0")
    try:
        prev_total = float(prev_total_raw)
    except Exception:
        prev_total = 0.0
    new_total = prev_total + total_day_yield
    doc_ref.update({
        "total_yield": str(round(new_total, 2)),
        "past_updated": formatted_train_time,
        "formatTimeUpdate": formatted_time_only,
        "year": formatted_year
    })
    print(f"[info] Updated monthlyYieldSummary for {first_of_month}.")
else:
    new_total = total_day_yield
    db.collection("monthlyYieldSummary").add({
        "month": first_of_month,
        "total_yield": str(round(new_total, 2)),
        "past_updated": formatted_train_time,
        "formatTimeUpdate": formatted_time_only,
        "year": formatted_year
    })
    print(f"[info] Created monthlyYieldSummary for {first_of_month}.")

# =========================================
# ✅ FORECAST NEXT PERIODS
# =========================================
try:
    daily_docs = db.collection("DailyReading") \
                   .order_by("date", direction=firestore.Query.DESCENDING) \
                   .limit(30).get()
    daily_yields = []
    for d in daily_docs:
        val = d.to_dict().get("total_yield", 0.0)
        try:
            daily_yields.append(float(val))
        except Exception:
            continue
except Exception as e:
    print(f"[warn] Failed to fetch DailyReading: {e}")
    daily_yields = []

avg_daily_yield = float(np.mean(daily_yields)) if daily_yields else total_day_yield

# Forecast 1, 2, 3 months (30-day blocks)
pred_1m = avg_daily_yield * 30
pred_2m = avg_daily_yield * 60
pred_3m = avg_daily_yield * 90

forecast_fields = {
    "month": first_of_month,
    "based_on_days": str(len(daily_yields)),
    "avg_daily_used": str(round(avg_daily_yield, 2)),
    "predicted_1month": str(round(pred_1m, 2)),
    "predicted_2months": str(round(pred_2m, 2)),
    "predicted_3months": str(round(pred_3m, 2)),
    "predicted_next_day": str(round(avg_daily_yield, 2)),
    "calculated_at": formatted_train_time,
    "forecast_generated_on": datetime.now(ph_tz)
}

# Upsert forecast into monthlyYieldSummary
existing_month = db.collection("monthlyYieldSummary").where("month", "==", first_of_month).limit(1).get()
if existing_month:
    existing_month[0].reference.set(forecast_fields, merge=True)
    print(f"[info] Updated monthlyYieldSummary for {first_of_month} with forecast fields.")
else:
    db.collection("monthlyYieldSummary").add(forecast_fields)
    print(f"[info] Created monthlyYieldSummary for {first_of_month} with forecast fields.")

# =========================================
# ✅ FINAL LOGS
# =========================================
print(f"✅ {len(predicted_yields)} predictions saved.")
print(f"📊 Total predicted yield for {today_iso}: {round(total_day_yield, 2)}")
print(f"📆 Monthly yield summary for {first_of_month}: {round(new_total, 2)}")
