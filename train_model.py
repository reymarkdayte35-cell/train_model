import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
import tensorflow as tf
from sklearn.preprocessing import StandardScaler
import numpy as np
from datetime import datetime
import pytz

# =====================================================
# 🔐 FIREBASE INIT (LOCAL OR GITHUB ACTIONS)
# =====================================================
if not firebase_admin._apps:
    if "FIREBASE_KEY" in os.environ:
        cred = credentials.Certificate(json.loads(os.environ["FIREBASE_KEY"]))
    else:
        cred = credentials.Certificate("CalamansiFirebaseKey.json")
    firebase_admin.initialize_app(cred)

db = firestore.client()

# =====================================================
# ⏰ TIME & FORMAT
# =====================================================
tz = pytz.timezone("Asia/Manila")
now = datetime.now(tz)

today_iso = now.strftime("%m-%d-%Y")
formatted_train_time = now.strftime("%Y-%m-%d %I:%M %p")
formatted_time_only = now.strftime("%I:%M %p")
formatted_year = str(now.year)
formatted_month = now.strftime("%Y-%m")  # YYYY-MM

# =====================================================
# CONFIG
# =====================================================
FARM_COLLECTION = "Farm_information"
SENSOR_COLLECTION = "dataCollectionSensor"
PREDICTED_COLLECTION = "predictedYield"

FARM_HARVEST_FIELD = "estimatedHarvest"
FARM_FLOWERING_FIELD = "floweringDate"

# =====================================================
# LOAD MODEL
# =====================================================
model = tf.keras.models.load_model("yield_model.keras")

# =====================================================
# FETCH SENSOR DATA
# =====================================================
docs = db.collection(SENSOR_COLLECTION).where("date", "==", today_iso).stream()

unlabeled_data = []
docs_to_update = []

for doc in docs:
    rec = doc.to_dict()
    if all(k in rec for k in ["temperature", "humidity", "avgSoilMoisture"]):
        try:
            unlabeled_data.append([
                float(rec["temperature"]),
                float(rec["humidity"]),
                float(rec["avgSoilMoisture"])
            ])
            docs_to_update.append((doc.id, rec))
        except Exception:
            continue

if not unlabeled_data:
    print("❌ No new sensor data today.")
    raise SystemExit(0)

# =====================================================
# SCALE & PREDICT
# =====================================================
scaler = StandardScaler()
X_scaled = scaler.fit_transform(np.array(unlabeled_data))
predicted_yields = model.predict(X_scaled).flatten()
total_day_yield = float(np.sum(predicted_yields))

# =====================================================
# INDEX COUNTER
# =====================================================
existing = db.collection(PREDICTED_COLLECTION).where("date", "==", today_iso).stream()
indices = []

for d in existing:
    try:
        indices.append(int(d.to_dict().get("index")))
    except Exception:
        continue

index_counter = max(indices, default=-1) + 1

# =====================================================
# SAVE PER-READING PREDICTIONS
# =====================================================
for i, (doc_id, original) in enumerate(docs_to_update):
    ts = datetime.now(tz)
    predicted = float(predicted_yields[i])

    db.collection(PREDICTED_COLLECTION).add({
        "temperature": str(original["temperature"]),
        "humidity": str(original["humidity"]),
        "avgSoilMoisture": str(original["avgSoilMoisture"]),
        "timestamp": ts,
        "date": today_iso,
        "time": ts.strftime("%I:%M %p"),
        "day": str(ts.day),
        "hour": str(ts.hour),
        "index": str(index_counter),
        "predicted_yield": str(round(predicted, 2)),
        "source": "predicted",
        "trained_at": formatted_train_time
    })

    index_counter += 1

    db.collection(SENSOR_COLLECTION).document(doc_id).update({
        "predicted": "True",
        "predicted_at": ts,
        "predicted_value": str(round(predicted, 4))
    })

# =====================================================
# DAILY READING
# =====================================================
db.collection("DailyReading").add({
    "date": today_iso,
    "total_yield": str(round(total_day_yield, 2)),
    "trained_at": formatted_train_time
})

# =====================================================
# FETCH FARM HARVEST & FLOWERING DATES (AS STRINGS)
# =====================================================
harvest_dates = []
flowering_dates = []

for fdoc in db.collection(FARM_COLLECTION).stream():
    fdata = fdoc.to_dict()
    if FARM_HARVEST_FIELD in fdata and fdata[FARM_HARVEST_FIELD]:
        harvest_dates.append(str(fdata[FARM_HARVEST_FIELD]))
    if FARM_FLOWERING_FIELD in fdata and fdata[FARM_FLOWERING_FIELD]:
        flowering_dates.append(str(fdata[FARM_FLOWERING_FIELD]))

# Join them into comma-separated strings
harvest_dates_str = ", ".join(sorted(harvest_dates)) if harvest_dates else ""
flowering_dates_str = ", ".join(sorted(flowering_dates)) if flowering_dates else ""

# =====================================================
# UPDATE MONTHLY YIELD SUMMARY
# =====================================================
monthly_ref = db.collection("monthlyYieldSummary")
monthly_docs = monthly_ref.where("month", "==", formatted_month).limit(1).get()

monthly_payload = {
    "month": formatted_month,
    "year": formatted_year,
    "total_yield": str(round(total_day_yield, 2)),
    "past_updated": formatted_train_time,
    "formatTimeUpdate": formatted_time_only,
    "harvestDate": harvest_dates_str,
    "floweringDate": flowering_dates_str
}

if monthly_docs:
    doc_ref = monthly_docs[0].reference
    prev_total = float(monthly_docs[0].to_dict().get("total_yield", 0))
    monthly_payload["total_yield"] = str(round(prev_total + total_day_yield, 2))
    doc_ref.set(monthly_payload, merge=True)
else:
    monthly_ref.add(monthly_payload)

# =====================================================
# FORECAST
# =====================================================
daily_docs = db.collection("DailyReading") \
    .order_by("date", direction=firestore.Query.DESCENDING) \
    .limit(30).get()

daily_vals = []
for d in daily_docs:
    try:
        daily_vals.append(float(d.to_dict().get("total_yield")))
    except Exception:
        continue

avg_daily = float(np.mean(daily_vals)) if daily_vals else total_day_yield

forecast_payload = {
    "avg_daily_used": str(round(avg_daily, 2)),
    "based_on_days": str(len(daily_vals)),
    "predicted_next_day": str(round(avg_daily, 2)),
    "predicted_1month": str(round(avg_daily * 30, 2)),
    "predicted_2months": str(round(avg_daily * 60, 2)),
    "predicted_3months": str(round(avg_daily * 90, 2)),
    "forecast_generated_on": datetime.now(tz),
    "calculated_at": formatted_train_time
}

# Merge forecast into monthly summary
monthly_docs = monthly_ref.where("month", "==", formatted_month).limit(1).get()
if monthly_docs:
    monthly_docs[0].reference.set(forecast_payload, merge=True)

# =====================================================
# FINAL LOGS
# =====================================================
print(f"✅ Predictions saved: {len(predicted_yields)}")
print(f"📊 Today Yield ({today_iso}): {round(total_day_yield, 2)}")
print(f"📆 Monthly Summary Updated: {formatted_month}")
print(f"🌾 Harvest Dates: {harvest_dates_str}")
print(f"🌸 Flowering Dates: {flowering_dates_str}")
