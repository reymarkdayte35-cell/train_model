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

HARVEST_FIELD_FARM = "estimatedHarvest"
HARVEST_FIELD_MONTHLY = "harvestDate"

PH_TZ = pytz.timezone("Asia/Manila")

# =====================================================
# 📅 DATE HELPERS
# =====================================================
def parse_date(date_str):
    """Convert 'Jan. 24, 2026' → date object"""
    try:
        return datetime.strptime(date_str.strip(), "%b. %d, %Y").date()
    except Exception:
        return None

# =====================================================
# 📅 TODAY
# =====================================================
now = datetime.now(PH_TZ)
today_date = now.date()
today_formatted = now.strftime("%b. %d, %Y").replace(" 0", " ")

print(f"📅 Today (formatted): {today_formatted}")
print(f"📅 Today (date obj): {today_date}\n")

# =====================================================
# 🔍 CHECK Farm_information FOR TODAY HARVEST
# =====================================================
matches = []

for doc in db.collection(FARM_COLLECTION).stream():
    data = doc.to_dict()
    harvest_str = data.get(HARVEST_FIELD_FARM)

    if not harvest_str:
        print(f"⚠️ {doc.id} → No {HARVEST_FIELD_FARM}")
        continue

    harvest_date = parse_date(harvest_str)

    print(f"📄 Farm Doc: {doc.id}")
    print(f"   🔹 estimatedHarvest: {harvest_str}")

    if harvest_date == today_date:
        print("   ✅ MATCHES TODAY — HARVEST DAY!\n")
        matches.append(doc.id)
    else:
        print("   ❌ Not today\n")

# =====================================================
# 🗑️ DELETE FROM monthlyYieldSummary
# =====================================================
deleted_count = 0

if matches:
    print("🗑️ Checking monthlyYieldSummary...\n")

    for mdoc in db.collection(MONTHLY_COLLECTION).stream():
        mdata = mdoc.to_dict()
        monthly_str = mdata.get(HARVEST_FIELD_MONTHLY)

        if not monthly_str:
            continue

        monthly_date = parse_date(monthly_str)

        print(f"📦 Monthly Doc: {mdoc.id}")
        print(f"   🔹 harvestDate: {monthly_str}")

        if monthly_date == today_date:
            print(f"   🧹 DELETING {mdoc.id}\n")
            mdoc.reference.delete()
            deleted_count += 1
        else:
            print("   ❌ Not today\n")

# =====================================================
# ✅ SUMMARY
# =====================================================
print("\n===================================")
if matches:
    print("🌱 FARMS WITH HARVEST TODAY:")
    for doc_id in matches:
        print(f" • {doc_id}")

    print(f"\n🗑️ TOTAL monthlyYieldSummary DELETED: {deleted_count}")
else:
    print("❌ No farms scheduled for harvest today")

print("===================================")
