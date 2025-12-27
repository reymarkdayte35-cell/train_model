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
firebase_key = json.loads(os.environ["FIREBASE_KEY"])

cred = credentials.Certificate(firebase_key)
firebase_admin.initialize_app(cred)

db = firestore.client()

if not firebase_key:
    raise ValueError("❌ FIREBASE_KEY environment variable not set. Please configure it in Render or GitHub Secrets.")

firebase_key = json.loads(firebase_key)

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
formatted_date = now.strftime("%m-%d-%Y")
formatted_year = now.strftime("%Y")
formatted_month = now.strftime("%Y-%m")
formatted_train_time = now.strftime("%Y-%m-%d %I:%M %p")
formatted_time_only = now.strftime("%I:%M %p")

# =========================================
# ✅ FETCH ONLY TODAY’S DATA
# =========================================

# ---------- Fetch sensor rows ----------
docs = (
    db.collection("dataCollectionSensor")
    .where("date", "==", formatted_date)
    .order_by("timestamp", direction=firestore.Query.DESCENDING)
    .stream()
)

# log training run (strings)
trained_at = datetime.now(ph_tz).strftime("%Y-%m-%d %I:%M %p")
db.collection("trainingLogs").add({
    "trained_at": str(trained_at),
    "note": str("Auto-retrain schedule")
})

# ---------- Prepare unlabeled data ----------
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
            # skip malformed rows
            continue

if not unlabeled_data:
    print("No new sensor data to predict.")
    raise SystemExit(0)

# ---------- Scale and predict ----------
scaler = StandardScaler()
X_scaled = scaler.fit_transform(np.array(unlabeled_data, dtype=float))
predicted_yields = model.predict(X_scaled).flatten()

# ---------- Determine index counter for today's predictedYield (keep as string) ----------
existing = db.collection("predictedYield").where("date", "==", formatted_date).stream()
existing_indices = []
for d in existing:
    idx = d.to_dict().get("index")
    try:
        existing_indices.append(int(idx))
    except Exception:
        pass
index_counter = max(existing_indices, default=-1) + 1

# ---------- Save per-reading predictions (store everything as strings) ----------
# total_day_yield = 0.0
# for i, (doc_id, original) in enumerate(docs_to_update):
#     timestamp = datetime.now(ph_tz)
#     formatted_time = timestamp.strftime("%I:%M %p")
#     hour_only = timestamp.strftime("%I")
#     day_only = str(timestamp.day)

#     predicted = float(predicted_yields[i])
#     total_day_yield += predicted

#     # write predicted record (all fields as strings)
#     db.collection("predictedYield").add({
#         "temperature": str(original.get("temperature")),
#         "humidity": str(original.get("humidity")),
#         "avgSoilMoisture": str(original.get("avgSoilMoisture")),
#         "timestamp": str(timestamp.isoformat()),
#         "date": str(formatted_date),
#         "time": str(formatted_time),
#         "day": str(day_only),
#         "hour": str(hour_only),
#         "index": str(index_counter),
#         "predicted_yield": str(round(predicted, 2)),
#         "source": str("predicted"),
#         "trained_at": str(formatted_train_time)
#     })

#     index_counter += 1

    # flag source sensor row as predicted (store strings)
    # try:
    #     db.collection("dataCollectionSensor").document(doc_id).update({
    #         "predicted": str("True"),
    #         "predicted_at": str(datetime.now(ph_tz).isoformat()),
    #         "predicted_value": str(round(predicted, 4))
    #     })
    # except Exception as e:
    #     print(f"[warn] failed to flag source doc {doc_id} as predicted: {e}")

# ---------- Save DailyReading (store strings) ----------
# db.collection("DailyReading").add({
#     "date": str(formatted_date),
#     "total_yield": str(round(total_day_yield, 2)),
#     "trained_at": str(formatted_train_time)
# })

# ---------- Monthly total upsert (read existing as string -> parse -> add -> store as string) ----------
first_of_month = formatted_month  # "YYYY-MM"
try:
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

        # update using strings
        doc_ref.update({
            "total_yield": str(round(new_total, 2)),
            "past_updated": str(formatted_train_time),
            "formatTimeUpdate": str(formatted_time_only),
            "year": str(formatted_year)
        })
        print(f"[info] Updated monthlyYieldSummary for {first_of_month}.")
    else:
        new_total = total_day_yield
        db.collection("monthlyYieldSummary").add({
            "month": str(first_of_month),
            "total_yield": str(round(new_total, 2)),
            "past_updated": str(formatted_train_time),
            "formatTimeUpdate": str(formatted_time_only),
            "year": str(formatted_year)
        })
        print(f"[info] Created monthlyYieldSummary for {first_of_month}.")
except Exception as e:
    print(f"⚠️ Failed to update monthly total: {e}")
    new_total = total_day_yield

# ---------- Build forecast basis from last 30 DailyReading rows (parse strings to floats if needed) ----------
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
            # if it's not parseable, skip
            pass
except Exception as e:
    print(f"[warn] Failed to fetch DailyReading: {e}")
    daily_yields = []

if daily_yields:
    avg_daily_yield = sum(daily_yields) / len(daily_yields)
else:
    avg_daily_yield = total_day_yield if total_day_yield else 0.0

# ---------- Predict next months (30-day blocks) and prepare forecast payload (strings) ----------
pred_1m = avg_daily_yield * 30.0
pred_2m = avg_daily_yield * 60.0
pred_3m = avg_daily_yield * 90.0

month_key = first_of_month
monthly_forecast_fields = {
    "month": str(month_key),
    "based_on_days": str(len(daily_yields)),
    "avg_daily_used": str(round(avg_daily_yield, 2)),
    "predicted_1month": str(round(pred_1m, 2)),
    "predicted_2months": str(round(pred_2m, 2)),
    "predicted_3months": str(round(pred_3m, 2)),
    "predicted_next_day": str(round(avg_daily_yield, 2)),
    "calculated_at": str(formatted_train_time),
    "forecast_generated_on": str(datetime.now(ph_tz).isoformat())
}

# Upsert forecast into monthlyYieldSummary (merge, store strings)
try:
    existing_month = db.collection("monthlyYieldSummary").where("month", "==", month_key).limit(1).get()
    if existing_month:
        existing_month[0].reference.set(monthly_forecast_fields, merge=True)
        print(f"[info] Updated monthlyYieldSummary for {month_key} with forecast fields.")
    else:
        db.collection("monthlyYieldSummary").add(monthly_forecast_fields)
        print(f"[info] Created monthlyYieldSummary for {month_key} with forecast fields.")
except Exception as e:
    print(f"[warn] Failed to upsert forecast into monthlyYieldSummary for {month_key}: {e}")

# ---------- Final logs ----------
print(f"✅ {len(predicted_yields)} predictions saved.")
print(f"📊 Total predicted yield for {formatted_date}: {str(round(total_day_yield, 2))}")
print(f"📆 Monthly yield summary for {formatted_month}: {str(round(new_total, 2))}")

