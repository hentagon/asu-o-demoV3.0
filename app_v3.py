"""
広報活動 データ登録アプリ V8.0 (前半)
V5.0詳細機能 ＋ 拠点別ログイン 融合版
"""

import streamlit as st
import json
from datetime import date

st.set_page_config(
    page_title="Asu o | 広報活動登録",
    page_icon="🗺",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# --- スタイル設定 (V5.0継承) ---
st.markdown("""
<style>
  html, body, [class*="css"] { font-family: 'Hiragino Sans', 'Noto Sans JP', sans-serif; }
  .app-title { font-size: 1.5rem; font-weight: 800; color: #1a472a; padding: 0.8rem 0 0.2rem; }
  .app-subtitle { font-size: 0.85rem; color: #666; margin-bottom: 1.2rem; }
  .login-box { background: #f4faf6; border: 1.5px solid #2d6a4f; border-radius: 16px; padding: 2rem; margin: 3rem auto; max-width: 360px; }
  .geo-badge { background: #E8F4FD; border: 1.5px solid #1565C0; border-radius: 10px; padding: 0.6rem 1rem; font-size: 0.9rem; color: #0D47A1; margin: 0.5rem 0; }
  .alarm-card { border: 2px solid #d00000; background: #fff5f5; padding: 10px; border-radius: 8px; color: #d00000; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# ============================================================
# 基本設定・関数
# ============================================================
DEFAULT_CENTER = [35.0116, 135.8514]
LOCATION_MAP = {
    "siga1": [35.0182, 135.8550], "siga2": [35.1283, 136.1031],
    "siga3": [35.0549, 135.9458], "siga4": [35.0182, 135.8550], "siga5": [35.0182, 135.8550],
}

@st.cache_resource
def get_supabase():
    try:
        from supabase import create_client
        return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    except Exception as e:
        st.error(f"DB接続エラー: {e}"); return None

def find_oaza_by_point(lon, lat, _supabase):
    if not _supabase: return "", ""
    try:
        res = _supabase.rpc("get_address_from_point", {"lng": lon, "lat": lat}).execute()
        if res.data: return res.data[0].get("city", ""), res.data[0].get("oaza", "")
    except Exception: pass
    return "", ""

def calc_centroid(geojson_dict):
    try:
        from shapely.geometry import shape
        c = shape(geojson_dict).centroid
        return c.x, c.y
    except Exception: return None

# ============================================================
# 地図生成 (レイヤー名日本語化 ＆ 安定版)
# ============================================================
# 地理院タイルの設定
MAP_TILES = "https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png"
PHOTO_TILES = "https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/{z}/{x}/{y}.jpg"
MAP_ATTR  = "国土地理院"

def make_base_map(draw_opts):
    import folium
    from folium.plugins import Draw
    center = st.session_state.get("map_center", DEFAULT_CENTER)
    
    # 最初の tiles を None にして、自分で TileLayer を追加することで名前を固定します
    m = folium.Map(location=center, zoom_start=15, tiles=None)
    
    # 標準地形図の追加
    folium.TileLayer(
        tiles=MAP_TILES, attr=MAP_ATTR, name="地形図", 
        control=True, overlay=False
    ).add_to(m)
    
    # 航空写真の追加
    folium.TileLayer(
        tiles=PHOTO_TILES, attr=MAP_ATTR, name="航空写真", 
        control=True, overlay=False, show=False
    ).add_to(m)
    
    folium.LayerControl(collapsed=False).add_to(m)
    Draw(draw_options=draw_opts, edit_options={"edit": True}).add_to(m)
    return m

# ============================================================
# 履歴用マップ生成 (完全ネイティブ・スクロール保持版)
# ============================================================
def make_review_map(points, polygons):
    import folium
    
    # 拠点に合わせて中心を移動
    center = st.session_state.get("map_center", DEFAULT_CENTER)
    m = folium.Map(location=center, zoom_start=13, tiles=None)

    # --- 背景地図（ラジオボタンで切り替え） ---
    folium.TileLayer(tiles=MAP_TILES, attr=MAP_ATTR, name="地形図", overlay=False, control=True).add_to(m)
    folium.TileLayer(tiles=PHOTO_TILES, attr=MAP_ATTR, name="航空写真", overlay=False, control=True, show=False).add_to(m)

    # --- データグループ（チェックボックスでON/OFF切り替え） ---
    fg_normal = folium.FeatureGroup(name="🟢 通常データ", show=True)
    fg_alarm  = folium.FeatureGroup(name="🚨 アラームデータ", show=True)

    def add_to_group(row, geom, is_poly=False):
        is_alarm = row.get("is_alarm", False)
        target_fg = fg_alarm if is_alarm else fg_normal
        popup_html = f"<b>{row.get('oaza_name','不明')}</b><br>{row.get('reaction','')}"
        
        if not is_poly:
            color = "red" if is_alarm else "green"
            icon_name = "exclamation-triangle" if is_alarm else "info-circle"
            folium.Marker(
                location=[geom["coordinates"][1], geom["coordinates"][0]],
                popup=folium.Popup(popup_html, max_width=200),
                icon=folium.Icon(color=color, icon=icon_name, prefix='fa')
            ).add_to(target_fg)
        else:
            c = "#d00000" if is_alarm else "#2d6a4f"
            folium.GeoJson(
                geom, 
                style_function=lambda x, color=c: {"fillColor":color, "color":color, "weight":2, "fillOpacity":0.4},
                popup=folium.Popup(popup_html, max_width=200)
            ).add_to(target_fg)

    # 定点とエリアの振り分け
    for row in points:
        geom_raw = row.get("geom")
        if not geom_raw: continue
        try:
            geom = json.loads(geom_raw) if isinstance(geom_raw, str) else geom_raw
            if geom and geom.get("type") == "Point": add_to_group(row, geom, is_poly=False)
        except: continue

    for row in polygons:
        geom_raw = row.get("geom")
        if not geom_raw: continue
        try:
            geom = json.loads(geom_raw) if isinstance(geom_raw, str) else geom_raw
            if geom: add_to_group(row, geom, is_poly=True)
        except: continue

    # グループを地図に追加し、最後にレイヤーコントロールを表示
    fg_normal.add_to(m)
    fg_alarm.add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
        
    return m

# ============================================================
# 認証
# ============================================================
if "authenticated" not in st.session_state: st.session_state.authenticated = False
if not st.session_state.authenticated:
    st.markdown('<div class="login-box">#### 🔑 拠点認証</div>', unsafe_allow_html=True)
    with st.form("login"):
        pwd = st.text_input("合言葉", type="password")
        if st.form_submit_button("ログイン"):
            if pwd in LOCATION_MAP:
                st.session_state.authenticated = True
                st.session_state.login_id = pwd
                st.session_state.map_center = LOCATION_MAP[pwd]
                st.rerun()
            else: st.error("認証失敗")
    st.stop()

# ============================================================
# セッション初期化 & タブ構成
# ============================================================
supabase = get_supabase()
for k in ["p_lon","p_lat","p_city","p_oaza","poly_geo","poly_city","poly_oaza","poly_cen"]:
    if k not in st.session_state: st.session_state[k] = None if "lon" in k or "lat" in k or "geo" in k or "cen" in k else ""

# --- ここから上書き ---
MATERIAL_TYPES = ["チラシA", "チラシB", "ポスター", "リーフレット", "その他"]
tab1, tab2, tab3 = st.tabs(["📌 定点配布", "🏘 戸別配布", "📋 登録履歴"])

# --- タブ1: 定点配布 ---
with tab1:
    from streamlit_folium import st_folium
    col_m, col_f = st.columns([3, 2])
    with col_m:
        st.markdown("**① 地図上に定点を置いてください**")
        out = st_folium(make_base_map({"marker":True,"polyline":False,"polygon":False,"rectangle":False,"circle":False,"circlemarker":False}), key="map_p", width=None, height=500)
        drawing = out.get("last_active_drawing")
        if drawing and drawing.get("geometry", {}).get("type") == "Point":
            lon, lat = drawing["geometry"]["coordinates"]
            if lon != st.session_state.p_lon:
                st.session_state.p_lon, st.session_state.p_lat = lon, lat
                st.session_state.p_city, st.session_state.p_oaza = find_oaza_by_point(lon, lat, supabase)
                st.rerun()
    with col_f:
        if st.session_state.p_lon:
            st.markdown(f'<div class="geo-badge">📍 {st.session_state.p_city} {st.session_state.p_oaza}</div>', unsafe_allow_html=True)
            with st.form("f_p", clear_on_submit=True):
                d = st.date_input("実施日", date.today())
                material_p = st.selectbox("資料種別", MATERIAL_TYPES, key="mp") # ★復活
                q = st.number_input("配布数量", 0)
                p = st.text_input("担当者名")
                st.markdown("---")
                resp = st.number_input("応答数", 0); attr = st.text_input("属性")
                alarm = st.checkbox("🚨 アラーム設定"); react = st.text_area("反応"); memo = st.text_area("備考")
                submit_p = st.form_submit_button("登録する", type="primary")
            
            # ★市町村・大字の手入力項目を復活
            col_cp, col_op = st.columns(2)
            with col_cp: city_p_input = st.text_input("市町村名", value=st.session_state.p_city, key="city_p_input")
            with col_op: oaza_p_input = st.text_input("大字名", value=st.session_state.p_oaza, key="oaza_p_input")

            if submit_p:
                payload = {
                    "ActivityDate": d.isoformat(), 
                    "MaterialType": material_p, # ★追加
                    "Quantity": q, "PIC": p, "is_alarm": alarm,
                    "geom": json.dumps({"type":"Point","coordinates":[st.session_state.p_lon, st.session_state.p_lat]}),
                    "city_name": city_p_input.strip() or st.session_state.p_city, # ★手入力を優先
                    "oaza_name": oaza_p_input.strip() or st.session_state.p_oaza, # ★手入力を優先
                    "response_count": resp, "target_attribute": attr, "reaction": react, "remarks": memo, "login_id": st.session_state.login_id
                }
                supabase.table("pr_points").insert(payload).execute()
                st.success("登録完了！"); st.session_state.p_lon = None; st.rerun()

# --- タブ2: 戸別配布 ---
with tab2:
    col_m2, col_f2 = st.columns([3, 2])
    with col_m2:
        st.markdown("**① 配布エリアを描いてください**")
        out_a = st_folium(make_base_map({"marker":False,"polyline":False,"polygon":True,"rectangle":True,"circle":False,"circlemarker":False}), key="map_a", width=None, height=500)
        drawing_a = out_a.get("last_active_drawing")
        if drawing_a and drawing_a.get("geometry", {}).get("type") in ("Polygon", "Rectangle"):
            geo = drawing_a["geometry"]
            if geo != st.session_state.poly_geo:
                st.session_state.poly_geo = geo
                cen = calc_centroid(geo)
                st.session_state.poly_cen = cen
                if cen:
                    st.session_state.poly_city, st.session_state.poly_oaza = find_oaza_by_point(cen[0], cen[1], supabase)
                st.rerun()
    with col_f2:
        if st.session_state.poly_geo:
            st.markdown(f'<div class="geo-badge">🏘 重心: {st.session_state.poly_city} {st.session_state.poly_oaza}</div>', unsafe_allow_html=True)
            with st.form("f_a", clear_on_submit=True):
                d = st.date_input("実施日", date.today(), key="da")
                material_a = st.selectbox("資料種別", MATERIAL_TYPES, key="ma") # ★復活
                q = st.number_input("配布数量", 0, key="qa")
                p = st.text_input("担当者名", key="pa")
                st.markdown("---")
                resp = st.number_input("応答数", 0, key="ra"); attr = st.text_input("属性", key="aa")
                alarm = st.checkbox("🚨 アラーム（要注意エリア）", key="ala")
                react = st.text_area("反応", key="rea"); memo = st.text_area("備考", key="mea")
                submit_a = st.form_submit_button("登録する", type="primary")

            # ★市町村・大字の手入力項目を復活
            col_ca, col_oa = st.columns(2)
            with col_ca: city_a_input = st.text_input("市町村名", value=st.session_state.poly_city, key="city_a_input")
            with col_oa: oaza_a_input = st.text_input("大字名", value=st.session_state.poly_oaza, key="oaza_a_input")

            if submit_a:
                payload = {
                    "ActivityDate": d.isoformat(), 
                    "MaterialType": material_a, # ★追加
                    "Quantity": q, "PIC": p, "is_alarm": alarm,
                    "geom": json.dumps(st.session_state.poly_geo), 
                    "city_name": city_a_input.strip() or st.session_state.poly_city, # ★手入力を優先
                    "oaza_name": oaza_a_input.strip() or st.session_state.poly_oaza, # ★手入力を優先
                    "response_count": resp, "target_attribute": attr, "reaction": react, "remarks": memo, "login_id": st.session_state.login_id
                }
                supabase.table("pr_areas").insert(payload).execute()
                st.success("エリア登録完了！"); st.session_state.poly_geo = None; st.rerun()

# --- タブ3: ダッシュボード ＆ 登録履歴 ---
with tab3:
    import pandas as pd
    from streamlit_folium import st_folium
    
    st.markdown("##### 📊 活動分析ダッシュボード")

    def show_df(data, title):
        if not data: return
        df = pd.DataFrame(data).drop(columns=["geom", "id", "centroid"], errors="ignore")
        df = df.rename(columns={
            "ActivityDate":"日付", "MaterialType":"資料", "Quantity":"数", 
            "PIC":"担当", "city_name":"市町村", "oaza_name":"大字", 
            "response_count":"応答", "target_attribute":"属性", 
            "reaction":"反応", "remarks":"備考", "is_alarm":"🚨", "login_id":"ログインID"
        })
        st.write(f"**{title}**")
        st.dataframe(df, use_container_width=True, hide_index=True)

    pts_raw = supabase.table("pr_points").select("*").order("ActivityDate", desc=True).execute().data or []
    ars_raw = supabase.table("pr_areas").select("*").order("ActivityDate", desc=True).execute().data or []

    df_pts = pd.DataFrame(pts_raw); df_ars = pd.DataFrame(ars_raw)
    df_all = pd.concat([df_pts, df_ars], ignore_index=True) if not (df_pts.empty and df_ars.empty) else pd.DataFrame()

    if not df_all.empty:
        df_all['Quantity'] = pd.to_numeric(df_all['Quantity'], errors='coerce').fillna(0)
        df_all['response_count'] = pd.to_numeric(df_all['response_count'], errors='coerce').fillna(0)
        
        c1, c2, c3 = st.columns(3)
        c1.metric("総配布数", f"{df_all['Quantity'].sum():,.0f} 部")
        c2.metric("総応答数", f"{df_all['response_count'].sum():,.0f} 件")
        c3.metric("🚨 アラーム", f"{df_all.get('is_alarm', pd.Series([False])).sum()} 件")
        st.markdown("---")

    # ============================================================
    # 🌟 修正ポイント：外部スイッチを廃止し、全データをネイティブマップへ渡す
    # ============================================================
    st.markdown("**🗺️ 活動・アラームマップ**")
    st.caption("💡 地図右上のメニューから「背景（地形図/航空写真）」と「表示データ」を切り替えられます。")
    
    # returned_objects=[] を指定し、クリックによる裏側の再通信をカット（超安定化）
    st_folium(
        make_review_map(pts_raw, ars_raw), 
        key="map_review_v12", 
        width=None, 
        height=500,
        returned_objects=[] 
    )

    if not df_all.empty:
        with st.expander("📋 登録データの詳細一覧を表示"):
            show_df(pts_raw, "📌 定点配布")
            show_df(ars_raw, "🏘 戸別配布")
    else:
        st.info("データがまだ登録されていません。")

# --- フッター ---
st.divider()
col_l, col_c, col_r = st.columns([3, 1, 3])
with col_c:
    if st.button("ログアウト"):
        st.session_state.clear(); st.rerun()