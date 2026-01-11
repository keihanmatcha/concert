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

    # 1. 位置情報の取得（ここは県名を補完して精度を上げる）
    geolocator = Nominatim(user_agent="rakuten_hotel_v4")
    query = f"日本 {place_name}"
    location = geolocator.geocode(query, timeout=10, language="ja")
    
    if not location:
        print(f"❌ {place_name} の位置が特定できませんでした。")
        return pd.DataFrame()
    
    print(f"📍 座標特定: {location.address} ({location.latitude}, {location.longitude})")

    # 2. 楽天API (座標で直接検索するモード)
    # エリアコード(middleClassCodeなど)を一切使わないのがコツです
    params = {
        "applicationId": RAKUTEN_APP_ID,
        "format": "json",
        "checkinDate": checkin,
        "checkoutDate": checkout,
        "latitude": location.latitude,   # 直接、緯度を入れる
        "longitude": location.longitude, # 直接、経度を入れる
        "searchRadius": radius,          # 指定した半径
        "datumType": 1,                  # 世界測地系
        "squeezeCondition": squeeze_cond,
        "hits": 30
    }

    res = requests.get("https://app.rakuten.co.jp/services/api/Travel/VacantHotelSearch/20170426", params=params)
    
    if res.status_code != 200:
        # 3km以内に1軒もない場合、楽天APIはエラーを返します
        print(f"⚠️ {place_name} の半径{radius}km以内に空室が見つかりませんでした。")
        return pd.DataFrame()

    # 以降、ホテルの解析処理...
    hotels = res.json().get("hotels", [])
    plans = []
    for h in hotels:
        h_data = h.get("hotel", [])
        if len(h_data) < 2: continue
        info = h_data[0]["hotelBasicInfo"]
        rooms = h_data[1].get("roomInfo", [])
        for i in range(0, len(rooms), 2):
            basic = rooms[i].get("roomBasicInfo", {})
            price = rooms[i+1].get("dailyCharge", {}).get("total")
            if price:
                plans.append({
                    "会場": place_name, "チェックイン": checkin, "ホテル名": info["hotelName"],
                    "料金": int(price), "予約URL": basic.get("reserveUrl")
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
