import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import pytz

cred = credentials.Certificate("CalamansiFirebaseKey.json")  # <-- your key file
firebase_admin.initialize_app(cred)

db = firestore.client()
# ---------------------------------------
# ⚙️ CONFIG
# ---------------------------------------
FARM_COLLECTION = "Farm_information"
HISTORY_COLLECTION = "farm_history"

DATE_FIELD = "estimatedHarvest"     # Farm_information
HISTORY_DATE_FIELD = "harvestDate"  # farm_history

PH_TZ = pytz.timezone("Asia/Manila")

# ---------------------------------------
# 📅 TODAY FORMATTED LIKE FIRESTORE
# ---------------------------------------
now = datetime.now(PH_TZ)

# Example: "Jan. 18, 2026"
today_formatted = now.strftime("%b. %d, %Y").replace(" 0", " ")
today_formatted1 = now.strftime("%B %d, %Y").replace(" 0", " ")
print(today_formatted)

print(today_formatted1)
print(f"\n📅 Today formatted: {today_formatted}\n")

# ---------------------------------------
# 🔍 CHECK Farm_information
# ---------------------------------------
matches = []

docs = db.collection(FARM_COLLECTION).stream()

for doc in docs:
    data = doc.to_dict()
    harvest_date = data.get(DATE_FIELD)

    if not harvest_date:
        print(f"⚠️ {doc.id} → No {DATE_FIELD}")
        continue

    print(f"📄 Doc: {doc.id}")
    print(f"   🔹 Stored estimatedHarvest: {harvest_date}")

    if harvest_date.strip() == today_formatted:
        print("   ✅ MATCHES TODAY — HARVEST DAY!\n")
        matches.append(doc.id)
    else:
        print("   ❌ Not today\n")

# ---------------------------------------
# 🗑️ DELETE FROM farm_history
# ---------------------------------------
deleted_count = 0

if matches:
    print("🗑️ Deleting matching records from farm_history...\n")

    history_docs = (
        db.collection(HISTORY_COLLECTION)
        .where(HISTORY_DATE_FIELD, "==", today_formatted)
        .stream()
    )
    
    history_docs = (
        db.collection(HISTORY_COLLECTION)
        .where(HISTORY_DATE_FIELD, "==", today_formatted1)
        .stream()
    )

    for hdoc in history_docs:
        print(f"🧹 Deleting farm_history doc → {hdoc.id}")
        hdoc.reference.delete()
        deleted_count += 1

# ---------------------------------------
# ✅ SUMMARY
# ---------------------------------------
print("\n===================================")
if matches:
    print("🌱 FARMS WITH HARVEST TODAY:")
    for doc_id in matches:
        print(f" • {doc_id}")

    print(f"\n🗑️ TOTAL farm_history RECORDS DELETED: {deleted_count}")
else:
    print("❌ No farms scheduled for harvest today")

print("===================================")
