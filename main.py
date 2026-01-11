import os
import pandas as pd
import requests
from geopy.geocoders import Nominatim
from datetime import date, datetime, timedelta

# --- 1. 環境変数から設定を取得 ---
PLACE_INPUT = os.environ.get("SEARCH_VENUE", "")
RAKUTEN_APP_ID = os.environ.get("RAKUTEN_APP_ID")
COND_INPUT = os.environ.get("SEARCH_COND", "")
try:
    RADIUS_INPUT = float(os.environ.get("SEARCH_RADIUS", "3.0"))
    if RADIUS_INPUT > 3.0: RADIUS_INPUT = 3.0
except:
    RADIUS_INPUT = 3.0

def main_search(place_name, checkin=None, checkout=None, radius=3.0, squeeze_cond=""):
    if not checkin: checkin = date.today().isoformat()
    if not checkout: checkout = (date.today() + timedelta(days=1)).isoformat()

    # --- ジオコーディング (日本語指定を追加) ---
    geolocator = Nominatim(user_agent="rakuten_hotel_search_v3")
    
    # 検索ワードに「Japan」だけでなく、もし県名がなければ補完する等の工夫
    query = place_name if "県" in place_name else f"宮城県 {place_name}"
    print(f"🔍 検索ワード: {query}")
    
    location = geolocator.geocode(query, timeout=10, language="ja")
    
    if not location:
        print(f"❌ {place_name} の位置が特定できませんでした。")
        return pd.DataFrame()
    
    print(f"📍 位置特定: {location.address}")
    print(f"📌 座標: ({location.latitude}, {location.longitude})")

    # --- 楽天API ---
    params = {
        "applicationId": RAKUTEN_APP_ID,
        "format": "json",
        "checkinDate": checkin,
        "checkoutDate": checkout,
        "latitude": location.latitude,
        "longitude": location.longitude,
        "searchRadius": radius,
        "datumType": 1,
        "squeezeCondition": squeeze_cond,
        "hits": 30
    }

    res = requests.get("https://app.rakuten.co.jp/services/api/Travel/VacantHotelSearch/20170426", params=params)
    
    if res.status_code != 200:
        data = res.json()
        if data.get("error") == "not_found":
            print(f"⚠️ 半径{radius}km以内に空室が見つかりませんでした。")
            print("💡 アドバイス: 楽天APIの仕様で最大3kmまでしか探せません。")
            print("   会場名ではなく『仙台駅』など、ホテルが多い駅名で検索してみてください。")
        else:
            print(f"❌ APIエラー: {data.get('error_description')}")
        return pd.DataFrame()

    hotels = res.json().get("hotels", [])
    plans = []
    for h in hotels:
        h_base = h.get("hotel", [])
        if len(h_base) < 2: continue
        info = h_base[0].get("hotelBasicInfo", {})
        rooms = h_base[1].get("roomInfo", [])
        for i in range(0, len(rooms), 2):
            basic = rooms[i].get("roomBasicInfo", {})
            price = rooms[i+1].get("dailyCharge", {}).get("total")
            if price:
                plans.append({
                    "会場": place_name, "ホテル名": info.get("hotelName"),
                    "料金": int(price), "評価": info.get("reviewAverage", 0), "予約URL": basic.get("reserveUrl")
                })
    return pd.DataFrame(plans)
    
# --- 4. 実行部分 ---
condition_map = {"禁煙": "kinen", "インターネット": "internet", "大浴場": "daiyoku", "温泉": "onsen", "朝食付き": "breakfast", "夕食付き": "dinner"}
squeeze_cond = ",".join([condition_map[c.strip()] for c in COND_INPUT.split(",") if c.strip() in condition_map])

venue_list = []
for line in PLACE_INPUT.splitlines():
    if not line.strip(): continue
    parts = [p.strip() for p in line.split(",")]
    if len(parts) >= 2:
        try:
            in_dt = datetime.strptime(parts[1], "%Y-%m-%d")
            out_dt = (in_dt + timedelta(days=1)).strftime("%Y-%m-%d")
            venue_list.append({"place": parts[0], "checkin": parts[1], "checkout": out_dt})
        except:
            venue_list.append({"place": parts[0]})
    else:
        venue_list.append({"place": parts[0]})

all_results = []
for v in venue_list:
    print(f"\n🔎 {v['place']} 周辺を検索中...")
    df = main_search(v["place"], v.get("checkin"), v.get("checkout"), RADIUS_INPUT, squeeze_cond)
    if not df.empty: all_results.append(df)

if all_results:
    final_df = pd.concat(all_results).sort_values("料金")
    print("\n" + final_df.to_markdown(index=False))
    final_df.to_csv("result.csv", index=False, encoding="utf-8-sig")
else:
    print("\n❌ 条件に合う空室が見つかりませんでした。")
    pd.DataFrame(columns=["会場", "結果"]).to_csv("result.csv", index=False)
