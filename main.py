import os
import json
import pandas as pd
import requests
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
from datetime import date, datetime, timedelta

# --- 1. 環境変数から設定を取得 ---
PLACE_INPUT = os.environ.get("SEARCH_VENUE", "セキスイハイムスーパーアリーナ, 2026-03-09")
COND_INPUT = os.environ.get("SEARCH_COND", "禁煙,朝食付き")
RAKUTEN_APP_ID = os.environ.get("RAKUTEN_APP_ID")

# --- 2. データの読み込みと初期化 ---
def initialize_data():
    with open("rakuten_area_class.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    records = []
    for large_entry in data["areaClasses"]["largeClasses"]:
        large_class_info = large_entry["largeClass"][0]
        l_code = large_class_info["largeClassCode"]
        l_name = large_class_info["largeClassName"]

        if len(large_entry["largeClass"]) < 2: continue
        
        for middle_entry in large_entry["largeClass"][1]["middleClasses"]:
            middle_class_info = middle_entry["middleClass"][0]
            m_code = middle_class_info["middleClassCode"]
            m_name = middle_class_info["middleClassName"]

            if len(middle_entry["middleClass"]) < 2: continue

            for small_entry in middle_entry["middleClass"][1]["smallClasses"]:
                small_class_info = small_entry["smallClass"][0]
                s_code = small_class_info["smallClassCode"]
                s_name = small_class_info["smallClassName"]

                if len(small_entry["smallClass"]) >= 2:
                    detail_data = small_entry["smallClass"][1]
                    if "detailClasses" in detail_data:
                        for detail_entry in detail_data["detailClasses"]:
                            d_class = detail_entry["detailClass"]
                            records.append({
                                "largeClassCode": l_code, "middleClassCode": m_code,
                                "smallClassCode": s_code, "detailClassCode": d_class["detailClassCode"],
                                "largeClassName": l_name, "middleClassName": m_name,
                                "smallClassName": s_name, "detailClassName": d_class["detailClassName"]
                            })
                    else:
                        records.append({
                            "largeClassCode": l_code, "middleClassCode": m_code,
                            "smallClassCode": s_code, "detailClassCode": "",
                            "largeClassName": l_name, "middleClassName": m_name,
                            "smallClassName": s_name, "detailClassName": s_name
                        })
    
    rakuten_df = pd.DataFrame(records)
    
    try:
        gaz_df = pd.read_csv("gazetteer-of-japan.csv")[["kanji", "lat", "lng"]]
    except Exception as e:
        print(f"⚠️ CSV読み込み警告: {e}")
        gaz_df = pd.DataFrame(columns=["kanji", "lat", "lng"])

    def lookup_latlon(detail_name):
        if not detail_name: return None, None
        for name in str(detail_name).split("・"):
            match = gaz_df[gaz_df["kanji"] == name]
            if not match.empty:
                return match.iloc[0]["lat"], match.iloc[0]["lng"]
        return None, None

    if not rakuten_df.empty:
        rakuten_df[["latitude", "longitude"]] = rakuten_df["detailClassName"].apply(
            lambda x: pd.Series(lookup_latlon(x))
        )
    
    return rakuten_df, gaz_df

rakuten_df, gaz_df = initialize_data()

# --- 3. 検索関数 ---
def find_nearest_rakuten_area(lat, lon, rakuten_df):
    min_dist, nearest = float("inf"), None
    for _, row in rakuten_df.iterrows():
        if pd.notnull(row["latitude"]):
            dist = geodesic((lat, lon), (row["latitude"], row["longitude"])).km
            if dist < min_dist:
                min_dist, nearest = dist, row.to_dict()
                nearest["matched_string"] = f"{dist:.2f}km"
    return nearest

def main_search(place_name, checkin=None, checkout=None, squeeze_cond=""):
    if not checkin: checkin = date.today().isoformat()
    if not checkout: checkout = (date.today() + timedelta(days=1)).isoformat()

    geolocator = Nominatim(user_agent="rakuten_search_bot")
    location = geolocator.geocode(place_name + ", Japan", timeout=10)
    
    if not location:
        print(f"❌ {place_name} の位置情報が取得できませんでした。")
        return pd.DataFrame()
    
    print(f"📍 座標取得: {place_name} ({location.latitude}, {location.longitude})")
    match = find_nearest_rakuten_area(location.latitude, location.longitude, rakuten_df)
    
    if not match:
        print(f"❌ 近隣の楽天エリアが見つかりませんでした。")
        return pd.DataFrame()
    
    print(f"🗺️ エリア判定: {match['largeClassName']} - {match['middleClassName']} - {match['smallClassName']}")

    params = {
        "applicationId": RAKUTEN_APP_ID,
        "format": "json",
        "checkinDate": checkin,
        "checkoutDate": checkout,
        "middleClassCode": match["middleClassCode"],
        "smallClassCode": match["smallClassCode"],
        "detailClassCode": match["detailClassCode"],
        "squeezeCondition": squeeze_cond,
        "hits": 30
    }

    res = requests.get("https://app.rakuten.co.jp/services/api/Travel/VacantHotelSearch/20170426", params=params)
    if res.status_code != 200:
        print(f"❌ APIエラー: {res.json().get('error_description', 'Unknown Error')}")
        return pd.DataFrame()

    hotels = res.json().get("hotels", [])
    plans = []
    for h in hotels:
        hotel_info = h["hotel"][0]["hotelBasicInfo"]
        room_info_list = h["hotel"][1].get("roomInfo", [])
        for i in range(0, len(room_info_list), 2):
            basic = room_info_list[i].get("roomBasicInfo", {})
            charge = room_info_list[i+1].get("dailyCharge", {})
            price = charge.get("total")
            if price:
                plans.append({
                    "会場": place_name, "チェックイン": checkin, "ホテル名": hotel_info["hotelName"],
                    "料金": int(price), "予約URL": basic.get("reserveUrl")
                })
    return pd.DataFrame(plans)

# --- 4. 実行ロジック（ここが抜けていました） ---

# こだわり条件の処理
condition_map = {"禁煙": "kinen", "インターネット": "internet", "大浴場": "daiyoku", "温泉": "onsen", "朝食付き": "breakfast", "夕食付き": "dinner"}
squeeze_cond = ",".join([condition_map[c.strip()] for c in COND_INPUT.split(",") if c.strip() in condition_map])

# 会場リストの作成
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

# 検索実行
all_results = []
for v in venue_list:
    print(f"\n--- 🔎 {v['place']} の検索開始 ---")
    res_df = main_search(v["place"], v.get("checkin"), v.get("checkout"), squeeze_cond)
    if not res_df.empty:
        all_results.append(res_df)

# ファイル保存
if all_results:
    final_df = pd.concat(all_results).sort_values("料金")
    print("\n### 🏨 検索結果一覧")
    print(final_df.to_markdown(index=False))
    final_df.to_csv("result.csv", index=False, encoding="utf-8-sig")
else:
    print("\n❌ 条件に合う空室が見つかりませんでした。")
    pd.DataFrame(columns=["会場", "結果"]).to_csv("result.csv", index=False)
