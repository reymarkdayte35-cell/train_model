import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import pytz

# =====================================================
# 🔐 FIREBASE INIT
# =====================================================
if not firebase_admin._apps:
    if "FIREBASE_KEY" in os.environ:
        cred = credentials.Certificate(json.loads(os.environ["FIREBASE_KEY"]))
    else:
        cred = credentials.Certificate("CalamansiFirebaseKey.json")
    firebase_admin.initialize_app(cred)

db = firestore.client()

# =====================================================
# ⚙️ CONFIG
# =====================================================
MONTHLY_COLLECTION = "monthlyYieldSummary"
FARM_COLLECTION = "Farm_information"

HARVEST_FIELD_FARM = "estimatedHarvest"  # field in Farm_information
HARVEST_FIELD_MONTHLY = "harvestDate"    # field in monthlyYieldSummary

PH_TZ = pytz.timezone("Asia/Manila")

# =====================================================
# 📅 TODAY FORMATTED LIKE Firestore
# =====================================================
now = datetime.now(PH_TZ)
today_formatted = now.strftime("%b. %d, %Y").replace(" 0", " ")
print(f"📅 Today formatted: {today_formatted}\n")

# =====================================================
# 🔍 CHECK Farm_information FOR TODAY HARVEST
# =====================================================
matches = []

docs = db.collection(FARM_COLLECTION).stream()

for doc in docs:
    data = doc.to_dict()
    harvest_date = data.get(HARVEST_FIELD_FARM)

    if not harvest_date:
        print(f"⚠️ {doc.id} → No {HARVEST_FIELD_FARM}")
        continue

    print(f"📄 Doc: {doc.id}")
    print(f"   🔹 Stored estimatedHarvest: {harvest_date}")

    if harvest_date.strip() == today_formatted:
        print("   ✅ MATCHES TODAY — HARVEST DAY!\n")
        matches.append(doc.id)
    else:
        print("   ❌ Not today\n")

# =====================================================
# 🗑️ DELETE FROM monthlyYieldSummary IF HARVEST MATCHES
# =====================================================
deleted_count = 0

if matches:
    print("🗑️ Deleting matching records from monthlyYieldSummary...\n")

    # Fetch all monthly summaries for the month/year
    monthly_docs = db.collection(MONTHLY_COLLECTION).stream()

    for mdoc in monthly_docs:
        mdata = mdoc.to_dict()
          monthly_harvest = mdata.get(HARVEST_FIELD_MONTHLY)
        if monthly_harvest and monthly_harvest.strip() == today_formatted:
            print(f"🧹 Deleting monthlyYieldSummary doc → {mdoc.id}")
            mdoc.reference.delete()
            deleted_count += 1

# =====================================================
# ✅ SUMMARY
# =====================================================
print("\n===================================")
if matches:
    print("🌱 FARMS WITH HARVEST TODAY (from Farm_information):")
    for doc_id in matches:
        print(f" • {doc_id}")

    print(f"\n🗑️ TOTAL monthlyYieldSummary RECORDS DELETED: {deleted_count}")
else:
    print("❌ No farms scheduled for harvest today")

print("===================================")




