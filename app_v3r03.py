"""
広報活動 データ登録アプリ V3.0
Streamlit + Folium(Draw) + Shapely + Supabase
地図上でポイント・ポリゴンを描画して登録
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

st.markdown("""
<style>
  html, body, [class*="css"] {
    font-family: 'Hiragino Sans', 'Noto Sans JP', sans-serif;
  }
  .app-title {
    font-size: 1.5rem; font-weight: 800;
    color: #1a472a; letter-spacing: 0.04em;
    padding: 0.8rem 0 0.2rem;
  }
  .app-subtitle { font-size: 0.85rem; color: #666; margin-bottom: 1.2rem; }
  .login-box {
    background: #f4faf6; border: 1.5px solid #2d6a4f;
    border-radius: 16px; padding: 2rem 1.5rem 1.5rem;
    margin: 3rem auto; max-width: 360px;
  }
  .stButton > button {
    width: 100%; height: 2.8rem; font-size: 1rem;
    font-weight: 700; border-radius: 10px;
  }
  .geo-badge {
    background: #E8F4FD; border: 1.5px solid #1565C0;
    border-radius: 10px; padding: 0.6rem 1rem;
    font-size: 0.9rem; line-height: 1.8; margin: 0.5rem 0;
    color: #0D47A1;
  }
  .success-card {
    background: #f0faf4; border: 1.5px solid #2d6a4f;
    border-radius: 10px; padding: 0.8rem 1.2rem;
    font-size: 0.9rem; line-height: 1.8; margin: 0.5rem 0;
  }
  .hint { color: #888; font-size: 0.8rem; margin-bottom: 0.5rem; }
</style>
""", unsafe_allow_html=True)


# ============================================================
# Supabase クライアント
# ============================================================
@st.cache_resource
def get_supabase():
    try:
        from supabase import create_client
        return create_client(
            st.secrets["SUPABASE_URL"],
            st.secrets["SUPABASE_KEY"]
        )
    except Exception as e:
        st.error(f"DB接続エラー: {e}")
        return None


# ============================================================
# 大字キャッシュ（全件取得・shapely判定）
# ============================================================
@st.cache_data(ttl=600, show_spinner="字界データを読み込み中...")
def load_oaza_bounds(_supabase) -> list[dict]:
    """
    oaza_boundsを全件取得してキャッシュする。
    geomカラムはGeoJSON文字列またはPostGIS形式で返ってくる想定。
    TTL=600秒（10分）でキャッシュ更新。
    """
    try:
        res = _supabase.table("oaza_bounds") \
            .select("id, city_name, s_name, geom") \
            .execute()
        return res.data or []
    except Exception as e:
        st.warning(f"字界データ取得エラー: {e}")
        return []


def find_oaza_by_point(lon: float, lat: float,
                       oaza_list: list[dict]) -> tuple[str, str]:
    """
    shapely を使って Point in Polygon 判定を行い
    （市町村名, 大字名）を返す。見つからない場合は ("", "")。
    """
    try:
        from shapely.geometry import Point, shape

        pt = Point(lon, lat)
        for row in oaza_list:
            geom_raw = row.get("geom")
            if not geom_raw:
                continue
            try:
                if isinstance(geom_raw, str):
                    geom_dict = json.loads(geom_raw)
                else:
                    geom_dict = geom_raw
                polygon = shape(geom_dict)
                if polygon.contains(pt):
                    return row.get("city_name", ""), row.get("s_name", "")
            except Exception:
                continue
    except ImportError:
        st.error("shapely がインストールされていません。requirements.txt を確認してください。")
    return "", ""


def calc_centroid(geojson_dict: dict) -> tuple[float, float] | None:
    """
    ポリゴンのGeoJSONから重心（lon, lat）を返す。
    """
    try:
        from shapely.geometry import shape
        polygon = shape(geojson_dict)
        c = polygon.centroid
        return c.x, c.y
    except Exception:
        return None


# ============================================================
# 地図ユーティリティ
# ============================================================

# 大津駅を地図の中心に設定
MAP_CENTER = [35.0116, 135.8514]
MAP_ZOOM   = 14
MAP_TILES  = "https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png"
MAP_ATTR   = "国土地理院"


def make_point_map(center: list[float] | None = None):
    """定点入力用 folium マップ（Markerのみ描画可）"""
    import folium
    from folium.plugins import Draw

    m = folium.Map(
        location=center or MAP_CENTER,
        zoom_start=MAP_ZOOM,
        tiles=MAP_TILES,
        attr=MAP_ATTR,
    )
    Draw(
        draw_options={
            "polyline": False, "polygon": False,
            "rectangle": False, "circle": False,
            "circlemarker": False, "marker": True,
        },
        edit_options={"edit": False},
    ).add_to(m)
    return m


def make_polygon_map(center: list[float] | None = None):
    """戸別配布入力用 folium マップ（Polygonのみ描画可）"""
    import folium
    from folium.plugins import Draw

    m = folium.Map(
        location=center or MAP_CENTER,
        zoom_start=MAP_ZOOM,
        tiles=MAP_TILES,
        attr=MAP_ATTR,
    )
    Draw(
        draw_options={
            "polyline": False, "polygon": True,
            "rectangle": True, "circle": False,
            "circlemarker": False, "marker": False,
        },
        edit_options={"edit": True},
    ).add_to(m)
    return m


def make_review_map(points: list[dict], polygons: list[dict]):
    """登録済みデータ確認用マップ（ポイント + ポリゴン表示）"""
    import folium

    m = folium.Map(
        location=MAP_CENTER,
        zoom_start=MAP_ZOOM,
        tiles=MAP_TILES,
        attr=MAP_ATTR,
    )

    for row in points:
        geom_raw = row.get("geom")
        if not geom_raw:
            continue
        try:
            geom = json.loads(geom_raw) if isinstance(geom_raw, str) else geom_raw
            if geom.get("type") == "Point":
                lon, lat = geom["coordinates"]
                popup_html = (
                    f"<b>{row.get('oaza_name','')} {row.get('city_name','')}</b><br>"
                    f"実施日: {row.get('ActivityDate','')}<br>"
                    f"資料: {row.get('MaterialType','')}<br>"
                    f"配布数: {row.get('Quantity',0):,} 部<br>"
                    f"担当: {row.get('PIC','')}"
                )
                folium.Marker(
                    location=[lat, lon],
                    popup=folium.Popup(popup_html, max_width=220),
                    tooltip=row.get("oaza_name", "定点"),
                    icon=folium.Icon(color="green", icon="map-marker"),
                ).add_to(m)
        except Exception:
            continue

    for row in polygons:
        geom_raw = row.get("geom")
        if not geom_raw:
            continue
        try:
            geom = json.loads(geom_raw) if isinstance(geom_raw, str) else geom_raw
            if geom.get("type") in ("Polygon", "MultiPolygon"):
                popup_html = (
                    f"<b>{row.get('oaza_name','')} {row.get('city_name','')}</b><br>"
                    f"実施日: {row.get('ActivityDate','')}<br>"
                    f"資料: {row.get('MaterialType','')}<br>"
                    f"配布数: {row.get('Quantity',0):,} 部<br>"
                    f"担当: {row.get('PIC','')}"
                )
                folium.GeoJson(
                    geom,
                    style_function=lambda _: {
                        "fillColor": "#2d6a4f", "color": "#1a472a",
                        "weight": 2, "fillOpacity": 0.35,
                    },
                    popup=folium.Popup(popup_html, max_width=220),
                    tooltip=row.get("oaza_name", "戸別エリア"),
                ).add_to(m)
        except Exception:
            continue

    return m


# ============================================================
# セッション状態の初期化
# ============================================================
if "authenticated"  not in st.session_state:
    st.session_state.authenticated  = False
if "point_lon"      not in st.session_state:
    st.session_state.point_lon      = None
if "point_lat"      not in st.session_state:
    st.session_state.point_lat      = None
if "point_city"     not in st.session_state:
    st.session_state.point_city     = ""
if "point_oaza"     not in st.session_state:
    st.session_state.point_oaza     = ""
if "polygon_geojson" not in st.session_state:
    st.session_state.polygon_geojson = None
if "polygon_city"   not in st.session_state:
    st.session_state.polygon_city   = ""
if "polygon_oaza"   not in st.session_state:
    st.session_state.polygon_oaza   = ""
if "polygon_centroid" not in st.session_state:
    st.session_state.polygon_centroid = None


# ============================================================
# タイトル
# ============================================================
st.markdown('<div class="app-title">🗺 Asu o ｜ 広報活動 データ登録</div>',
            unsafe_allow_html=True)
st.markdown(
    '<div class="app-subtitle">地図上で活動場所を選んで、チラシ配布の記録を登録できます</div>',
    unsafe_allow_html=True
)


# ============================================================
# 合言葉認証
# ============================================================
PASSPHRASE = "nora"

if not st.session_state.authenticated:
    st.markdown('<div class="login-box">', unsafe_allow_html=True)
    st.markdown("#### 🔑 合言葉を入力してください")
    st.caption("このアプリを利用するには合言葉が必要です。")
    with st.form("login_form"):
        entered = st.text_input(
            "合言葉", type="password",
            placeholder="合言葉を入力",
            label_visibility="collapsed",
        )
        login_btn = st.form_submit_button("確認する", type="primary")
    if login_btn:
        if entered == PASSPHRASE:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("合言葉が違います。もう一度お試しください。")
    st.markdown('</div>', unsafe_allow_html=True)
    st.stop()


# ============================================================
# 認証後：メインコンテンツ
# ============================================================
supabase   = get_supabase()
oaza_list  = load_oaza_bounds(supabase) if supabase else []

MATERIAL_TYPES = ["チラシA", "チラシB", "ポスター", "リーフレット", "その他"]

tab1, tab2, tab3 = st.tabs([
    "📌 定点配布の登録",
    "🏘 戸別配布の登録",
    "📋 登録済みデータ一覧",
])


# ============================================================
# タブ1：定点配布（ポイント入力）
# ============================================================
with tab1:
    try:
        from streamlit_folium import st_folium
    except ImportError:
        st.error("streamlit-folium がインストールされていません。requirements.txt を確認してください。")
        st.stop()

    col_map, col_form = st.columns([3, 2])

    with col_map:
        st.markdown("**① 地図上に定点を置いてください**")
        st.markdown(
            '<p class="hint">📍 左上の点マーカーツールを選んで、配布場所をクリックしてください</p>',
            unsafe_allow_html=True
        )

        # 地図表示
        m_point = make_point_map()
        map_data_p = st_folium(
            m_point,
            key="map_point",
            width=None,
            height=420,
            returned_objects=["last_active_drawing"],
        )

        # 描画結果の取得
        drawing = map_data_p.get("last_active_drawing")
        if drawing and drawing.get("geometry", {}).get("type") == "Point":
            coords = drawing["geometry"]["coordinates"]
            lon, lat = float(coords[0]), float(coords[1])

            if (lon != st.session_state.point_lon or
                    lat != st.session_state.point_lat):
                st.session_state.point_lon  = lon
                st.session_state.point_lat  = lat

                # 大字の逆引き
                with st.spinner("大字を検索中..."):
                    city, oaza = find_oaza_by_point(lon, lat, oaza_list)
                st.session_state.point_city = city
                st.session_state.point_oaza = oaza
                st.rerun()

    with col_form:
        st.markdown("**② 活動内容を入力して登録**")

        # 座標・大字の表示
        if st.session_state.point_lon is not None:
            st.markdown(
                f'<div class="geo-badge">'
                f'📍 <b>緯度:</b> {st.session_state.point_lat:.6f}<br>'
                f'📍 <b>経度:</b> {st.session_state.point_lon:.6f}<br>'
                f'🏙 <b>市町村:</b> {st.session_state.point_city or "（未一致）"}<br>'
                f'📌 <b>大字:</b> {st.session_state.point_oaza or "（未一致）"}'
                f'</div>',
                unsafe_allow_html=True
            )
        else:
            st.info("地図上に定点を置くと、市町村・大字が自動で入力されます。")

        with st.form("form_points", clear_on_submit=True):
            act_date_p = st.date_input("実施日", value=date.today(), key="dp")
            material_p = st.selectbox("資料種別", MATERIAL_TYPES, key="mp")
            quantity_p = st.number_input(
                "配布数量（部）", min_value=0, max_value=99999,
                step=1, value=0, key="qp"
            )
            pic_p = st.text_input("担当者名", placeholder="例: 山田 太郎", key="pp")

            col_cp, col_op = st.columns(2)
            with col_cp:
                city_p_input = st.text_input(
                    "市町村名",
                    value=st.session_state.point_city,
                    placeholder="例: 大津市",
                    key="city_p_input",
                    help="字界データから自動取得。未取得時は手入力してください。",
                )
            with col_op:
                oaza_p_input = st.text_input(
                    "大字名",
                    value=st.session_state.point_oaza,
                    placeholder="例: 唐崎",
                    key="oaza_p_input",
                    help="字界データから自動取得。未取得時は手入力してください。",
                )

            submit_p = st.form_submit_button("📌 定点配布を登録する", type="primary")

        if submit_p:
            errors = []
            if st.session_state.point_lon is None:
                errors.append("地図上に定点を置いてください。")
            if not pic_p.strip():
                errors.append("担当者名を入力してください。")
            if quantity_p <= 0:
                errors.append("配布数量は1以上を入力してください。")

            if errors:
                for e in errors:
                    st.warning(e)
            elif supabase is None:
                st.error("データベースに接続できません。")
            else:
                geojson_str = json.dumps({
                    "type": "Point",
                    "coordinates": [
                        st.session_state.point_lon,
                        st.session_state.point_lat
                    ]
                })
                # 手入力値を優先、なければ自動取得値を使用
                final_city_p = city_p_input.strip() or st.session_state.point_city
                final_oaza_p = oaza_p_input.strip() or st.session_state.point_oaza
                payload = {
                    "ActivityDate": act_date_p.isoformat(),
                    "MaterialType": material_p,
                    "Quantity":     int(quantity_p),
                    "PIC":          pic_p.strip(),
                    "geom":         geojson_str,
                    "city_name":    final_city_p,
                    "oaza_name":    final_oaza_p,
                }
                try:
                    res = supabase.table("pr_points").insert(payload).execute()
                    if res.data:
                        st.success("✅ 定点配布を登録しました！")
                        st.markdown(
                            f'<div class="success-card">'
                            f'<b>実施日:</b> {act_date_p.strftime("%Y年%m月%d日")}<br>'
                            f'<b>資料種別:</b> {material_p}<br>'
                            f'<b>配布数量:</b> {quantity_p:,} 部<br>'
                            f'<b>担当者名:</b> {pic_p.strip()}<br>'
                            f'<b>市町村:</b> {final_city_p or "―"}<br>'
                            f'<b>大字:</b> {final_oaza_p or "―"}'
                            f'</div>',
                            unsafe_allow_html=True
                        )
                        # 座標リセット
                        st.session_state.point_lon  = None
                        st.session_state.point_lat  = None
                        st.session_state.point_city = ""
                        st.session_state.point_oaza = ""
                    else:
                        st.error("登録に失敗しました。")
                except Exception as e:
                    st.error(f"登録エラー: {e}")


# ============================================================
# タブ2：戸別配布（ポリゴン入力）
# ============================================================
with tab2:
    try:
        from streamlit_folium import st_folium
    except ImportError:
        st.error("streamlit-folium がインストールされていません。")
        st.stop()

    col_map2, col_form2 = st.columns([3, 2])

    with col_map2:
        st.markdown("**① 配布エリアを地図上に描いてください**")
        st.markdown(
            '<p class="hint">🖊 左上の多角形ツールで配布エリアの外周をなぞってください</p>',
            unsafe_allow_html=True
        )

        m_poly = make_polygon_map()
        map_data_a = st_folium(
            m_poly,
            key="map_poly",
            width=None,
            height=420,
            returned_objects=["last_active_drawing"],
        )

        drawing_a = map_data_a.get("last_active_drawing")
        if drawing_a:
            geom_type = drawing_a.get("geometry", {}).get("type", "")
            if geom_type in ("Polygon", "Rectangle"):
                geojson_dict = drawing_a.get("geometry")

                if geojson_dict != st.session_state.polygon_geojson:
                    st.session_state.polygon_geojson = geojson_dict

                    # 重心計算
                    centroid = calc_centroid(geojson_dict)
                    st.session_state.polygon_centroid = centroid

                    if centroid:
                        clon, clat = centroid
                        with st.spinner("大字を検索中..."):
                            city, oaza = find_oaza_by_point(clon, clat, oaza_list)
                        st.session_state.polygon_city = city
                        st.session_state.polygon_oaza = oaza
                    else:
                        st.session_state.polygon_city = ""
                        st.session_state.polygon_oaza = ""
                    st.rerun()

    with col_form2:
        st.markdown("**② 活動内容を入力して登録**")

        if st.session_state.polygon_geojson:
            centroid = st.session_state.polygon_centroid
            if centroid:
                clon, clat = centroid
                st.markdown(
                    f'<div class="geo-badge">'
                    f'🔵 <b>重心 緯度:</b> {clat:.6f}<br>'
                    f'🔵 <b>重心 経度:</b> {clon:.6f}<br>'
                    f'🏙 <b>市町村:</b> {st.session_state.polygon_city or "（未一致）"}<br>'
                    f'📌 <b>大字:</b> {st.session_state.polygon_oaza or "（未一致）"}'
                    f'</div>',
                    unsafe_allow_html=True
                )
        else:
            st.info("地図上にエリアを描くと、重心から市町村・大字が自動で入力されます。")

        with st.form("form_areas", clear_on_submit=True):
            act_date_a = st.date_input("実施日", value=date.today(), key="da")
            material_a = st.selectbox("資料種別", MATERIAL_TYPES, key="ma")
            quantity_a = st.number_input(
                "配布数量（部）", min_value=0, max_value=99999,
                step=1, value=0, key="qa"
            )
            pic_a = st.text_input("担当者名", placeholder="例: 鈴木 花子", key="pa")

            col_ca, col_oa = st.columns(2)
            with col_ca:
                city_a_input = st.text_input(
                    "市町村名",
                    value=st.session_state.polygon_city,
                    placeholder="例: 大津市",
                    key="city_a_input",
                    help="字界データから自動取得。未取得時は手入力してください。",
                )
            with col_oa:
                oaza_a_input = st.text_input(
                    "大字名",
                    value=st.session_state.polygon_oaza,
                    placeholder="例: 唐崎",
                    key="oaza_a_input",
                    help="字界データから自動取得。未取得時は手入力してください。",
                )

            submit_a = st.form_submit_button("🏘 戸別配布を登録する", type="primary")

        if submit_a:
            errors = []
            if not st.session_state.polygon_geojson:
                errors.append("地図上にポリゴンを描いてください。")
            if not pic_a.strip():
                errors.append("担当者名を入力してください。")
            if quantity_a <= 0:
                errors.append("配布数量は1以上を入力してください。")

            if errors:
                for e in errors:
                    st.warning(e)
            elif supabase is None:
                st.error("データベースに接続できません。")
            else:
                centroid     = st.session_state.polygon_centroid
                centroid_str = None
                if centroid:
                    clon, clat = centroid
                    centroid_str = json.dumps({
                        "type": "Point",
                        "coordinates": [clon, clat]
                    })

                # 手入力値を優先、なければ自動取得値を使用
                final_city_a = city_a_input.strip() or st.session_state.polygon_city
                final_oaza_a = oaza_a_input.strip() or st.session_state.polygon_oaza
                payload = {
                    "ActivityDate":  act_date_a.isoformat(),
                    "MaterialType":  material_a,
                    "Quantity":      int(quantity_a),
                    "PIC":           pic_a.strip(),
                    "geom":          json.dumps(st.session_state.polygon_geojson),
                    "centroid":      centroid_str,
                    "city_name":     final_city_a,
                    "oaza_name":     final_oaza_a,
                }
                try:
                    res = supabase.table("pr_areas").insert(payload).execute()
                    if res.data:
                        st.success("✅ 戸別配布を登録しました！")
                        st.markdown(
                            f'<div class="success-card">'
                            f'<b>実施日:</b> {act_date_a.strftime("%Y年%m月%d日")}<br>'
                            f'<b>資料種別:</b> {material_a}<br>'
                            f'<b>配布数量:</b> {quantity_a:,} 部<br>'
                            f'<b>担当者名:</b> {pic_a.strip()}<br>'
                            f'<b>市町村:</b> {final_city_a or "―"}<br>'
                            f'<b>大字:</b> {final_oaza_a or "―"}'
                            f'</div>',
                            unsafe_allow_html=True
                        )
                        # ポリゴンリセット
                        st.session_state.polygon_geojson  = None
                        st.session_state.polygon_centroid = None
                        st.session_state.polygon_city     = ""
                        st.session_state.polygon_oaza     = ""
                    else:
                        st.error("登録に失敗しました。")
                except Exception as e:
                    st.error(f"登録エラー: {e}")


# ============================================================
# タブ3：登録済みデータ一覧（地図表示付き）
# ============================================================
with tab3:
    import pandas as pd
    from streamlit_folium import st_folium

    st.markdown("##### 登録済みデータの確認")

    # --- フィルター ---
    col_f1, col_f2, col_f3, col_f4 = st.columns([2, 2, 2, 1])
    with col_f1:
        d_from_t3 = st.date_input("開始日", value=None, key="t3_from",
                                   label_visibility="collapsed")
    with col_f2:
        pic_t3 = st.text_input("担当者名で絞込み", placeholder="担当者名（空白で全件）",
                                key="t3_pic")
    with col_f3:
        oaza_t3 = st.text_input("大字名で絞込み", placeholder="大字名（空白で全件）",
                                 key="t3_oaza")
    with col_f4:
        load_t3 = st.button("🔍 表示", key="t3_load", type="primary")

    if load_t3:
        if supabase is None:
            st.error("DB接続エラー")
        else:
            # 定点・戸別を両方取得
            def fetch_table(table: str) -> list[dict]:
                q = (supabase.table(table)
                     .select("ActivityDate, MaterialType, Quantity, PIC, "
                             "city_name, oaza_name, geom, created_at")
                     .order("ActivityDate", desc=True)
                     .limit(300))
                if d_from_t3:
                    q = q.gte("ActivityDate", d_from_t3.isoformat())
                if pic_t3.strip():
                    q = q.ilike("PIC", f"%{pic_t3.strip()}%")
                if oaza_t3.strip():
                    q = q.ilike("oaza_name", f"%{oaza_t3.strip()}%")
                try:
                    return q.execute().data or []
                except Exception as e:
                    st.error(f"{table} 取得エラー: {e}")
                    return []

            pts_data  = fetch_table("pr_points")
            poly_data = fetch_table("pr_areas")

            # --- 地図表示 ---
            st.markdown("**登録済みデータの地図表示**")
            st.caption("緑のピン：定点配布　緑のポリゴン：戸別配布　（クリックで詳細表示）")

            review_map = make_review_map(pts_data, poly_data)
            st_folium(review_map, key="map_review", width=None, height=460,
                      returned_objects=[])

            # --- テーブル表示 ---
            sub1, sub2 = st.tabs(["📌 定点配布", "🏘 戸別配布"])

            def show_table(data: list[dict]):
                if not data:
                    st.info("該当データがありません。")
                    return
                df = pd.DataFrame(data).rename(columns={
                    "ActivityDate": "実施日",
                    "MaterialType": "資料種別",
                    "Quantity":     "配布数量",
                    "PIC":          "担当者名",
                    "city_name":    "市町村",
                    "oaza_name":    "大字",
                    "created_at":   "登録日時",
                }).drop(columns=["geom"], errors="ignore")

                total = int(df["配布数量"].sum())
                st.caption(f"**{len(df)} 件 ／ 合計 {total:,} 部**")
                st.dataframe(
                    df, use_container_width=True, hide_index=True,
                    column_config={
                        "配布数量": st.column_config.NumberColumn(format="%d 部"),
                        "登録日時": st.column_config.DatetimeColumn(
                            format="YYYY/MM/DD HH:mm"),
                    }
                )

            with sub1:
                show_table(pts_data)
            with sub2:
                show_table(poly_data)
    else:
        st.info("絞り込み条件を設定して「表示」ボタンを押してください。")


# ============================================================
# フッター
# ============================================================
st.divider()
col1, col2, col3 = st.columns([3, 1, 3])
with col2:
    if st.button("ログアウト"):
        for key in ["authenticated", "point_lon", "point_lat",
                    "point_city", "point_oaza",
                    "polygon_geojson", "polygon_city",
                    "polygon_oaza", "polygon_centroid"]:
            st.session_state[key] = False if key == "authenticated" else None \
                if "lon" in key or "lat" in key or "geojson" in key \
                or "centroid" in key else ""
        st.rerun()
