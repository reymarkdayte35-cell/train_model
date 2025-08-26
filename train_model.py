import firebase_admin
from firebase_admin import credentials, firestore
import tensorflow as tf
from sklearn.preprocessing import StandardScaler
import numpy as np
from datetime import datetime
import pytz


# ✅ Initialize Firebase
cred = credentials.Certificate("firebase_key.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

# ✅ Load trained model
model = tf.keras.models.load_model("yield_model.keras")

# ✅ Get current Philippine time
ph_tz = pytz.timezone("Asia/Manila")
now = datetime.now(ph_tz)
formatted_date = now.strftime("%m/%d/%Y")
formatted_year = now.strftime("yy")         # e.g. 07/23/2025
formatted_month = now.strftime("%Y-%m")            # e.g. 2025-07
formatted_train_time = now.strftime("%Y-%m-%d %I:%M %p")
formatted_time_only = now.strftime("%I:%M %p")  # e.g., 02:14 PM


# ✅ Fetch only today’s data
docs = (
    db.collection("dataCollectionSensor")
    .where("date", "==", formatted_date)
    .order_by("timestamp", direction=firestore.Query.DESCENDING)
    .stream()
)
trained_at = datetime.now(pytz.timezone("Asia/Manila")).strftime("%Y-%m-%d %I:%M %p")

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

# ✅ Scale and predict
scaler = StandardScaler()
X_scaled = scaler.fit_transform(unlabeled_data)
predicted_yields = model.predict(X_scaled).flatten()

# ✅ Determine max index so far for today
existing = db.collection("predictedYield").where("date", "==", formatted_date).stream()
existing_indices = [int(doc.to_dict().get("index", 0)) for doc in existing]
index_counter = max(existing_indices, default=-1) + 1

# ✅ Save predictions and accumulate total
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


# ✅ Save to DailyReading (📘 NEW)
db.collection("DailyReading").add({
    "date": formatted_date,
    "total_yield": round(total_day_yield, 2),
    "trained_at": formatted_train_time
})

timestamp_str = record.get("timestamp")  # e.g., "2025-08-05 14:30:00"
if timestamp_str:
    try:
        year = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S").year
        print("Year:", year)
    except ValueError:
        print("Invalid timestamp format")

# Convert formatted_month to a proper datetime (1st of month)
first_of_month = formatted_month 

try:
    # Query for existing doc with this month
    monthly_docs = db.collection("monthlyYieldSummary").where("month", "==", first_of_month).get()

    if monthly_docs:
        print(f"update this month") 
        monthly_doc = monthly_docs[0]
        doc_ref = monthly_doc.reference
        prev_total = monthly_doc.to_dict().get("total_yield", 0)
        new_total = prev_total + total_day_yield

        doc_ref.update({
            "total_yield": round(new_total, 2),
            "past_updated": formatted_train_time,
            "formatTimeUpdate": formatted_time_only,
            "year": year
        })
    else:
        print(f"Create new month")
        new_total = total_day_yield
        db.collection("monthlyYieldSummary").add({
            "month": first_of_month,
            "total_yield": round(new_total, 2),
            "past_updated": formatted_train_time,
            "formatTimeUpdate": formatted_time_only,
            "year": year
        })

except Exception as e:
    print(f"⚠️ Failed to update monthly total: {e}")
    new_total = total_day_yield  # Ensure it's defined for printing



# ✅ Final logs
print(f"✅ {len(predicted_yields)} predictions saved.")
print(f"📊 Total predicted yield for {formatted_date}: {round(total_day_yield, 2)}")
print(f"📆 Monthly yield summary for {formatted_month}: {round(new_total, 2)}")
