"""
Harbinger eBay リサーチ（スマホ対応版）
streamlit run app.py で起動
"""
import streamlit as st
import pandas as pd
import json
import os
from datetime import datetime, timedelta
from recommend import research_stocked, research_dropship

st.set_page_config(
    page_title="Harbinger eBay",
    page_icon="📦",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ── スマホ最適化CSS ──────────────────────────────────────
st.markdown("""
<style>
  /* 全体フォントサイズ */
  html, body, [class*="css"] { font-size: 15px; }

  /* ボタンを大きく */
  .stButton > button {
    width: 100%;
    height: 3.2rem;
    font-size: 1rem;
    font-weight: bold;
    border-radius: 10px;
  }

  /* カード */
  .card {
    background: #fff;
    border-radius: 12px;
    padding: 14px 16px;
    margin-bottom: 12px;
    border-left: 5px solid #F4821E;
    box-shadow: 0 2px 6px rgba(0,0,0,0.08);
  }
  .card.green  { border-left-color: #2E7D32; }
  .card.blue   { border-left-color: #1E88E5; }
  .card.red    { border-left-color: #C62828; }
  .card.purple { border-left-color: #7B1FA2; }
  .card.gray   { border-left-color: #757575; }

  .card-title  { font-size: 1rem; font-weight: bold; margin-bottom: 6px; }
  .card-genre  { font-size: 0.75rem; color: #888; margin-bottom: 8px; }
  .metric-row  { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }
  .metric-chip {
    background: #F5F5F5;
    border-radius: 6px;
    padding: 3px 8px;
    font-size: 0.8rem;
  }
  .metric-chip.ok  { background: #E8F5E9; color: #2E7D32; font-weight: bold; }
  .metric-chip.bad { background: #FFEBEE; color: #C62828; }
  .profit-big {
    font-size: 1.3rem;
    font-weight: bold;
    color: #2E7D32;
  }
  .profit-bad { color: #C62828; }
  .badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 0.75rem;
    font-weight: bold;
    margin-bottom: 8px;
  }
  .badge.ok  { background: #2E7D32; color: white; }
  .badge.ng  { background: #FF9800; color: white; }

  /* タブ */
  .stTabs [data-baseweb="tab"] { font-size: 0.9rem; padding: 8px 12px; }

  /* メトリクス */
  [data-testid="metric-container"] { background: #F9F9F9; border-radius: 8px; padding: 8px; }
</style>
""", unsafe_allow_html=True)

# ── キャッシュ ────────────────────────────────────────────
CACHE_FILE = os.path.join(os.path.dirname(__file__), ".research_cache.json")
CACHE_DAYS = 7

def load_cache():
    if not os.path.exists(CACHE_FILE):
        return None, None, None
    try:
        with open(CACHE_FILE) as f:
            data = json.load(f)
        updated_at = datetime.fromisoformat(data["updated_at"])
        return data.get("stocked"), data.get("dropship"), updated_at
    except Exception:
        return None, None, None

def save_cache(stocked, dropship):
    with open(CACHE_FILE, "w") as f:
        json.dump({
            "updated_at": datetime.now().isoformat(),
            "stocked": stocked,
            "dropship": dropship,
        }, f, ensure_ascii=False)

def is_expired(updated_at):
    if updated_at is None: return True
    return datetime.now() - updated_at > timedelta(days=CACHE_DAYS)

# ── カード表示 ────────────────────────────────────────────
COLOR_MAP = ["", "green", "blue", "red", "purple", "gray"]

def render_cards(results: list):
    if not results:
        st.info("データなし")
        return

    for i, r in enumerate(results):
        meets   = r.get("meets_all", False)
        col_cls = COLOR_MAP[i % len(COLOR_MAP)]
        badge   = '<span class="badge ok">🟢 全条件達成</span>' if meets else '<span class="badge ng">🟡 要確認</span>'
        profit_cls = "" if r["profit"] >= 0 else " profit-bad"

        enc_kw = r['keyword'].replace(' ', '+')
        fallback_sold_url = f"https://www.ebay.com/sch/i.html?_nkw={enc_kw}&LH_Complete=1&LH_Sold=1&_ipg=60"
        sold_url = r.get("sold_url") or fallback_sold_url

        # データ品質バッジ
        is_real = r.get("data_source") == "sold_real"
        data_badge = (
            '<span style="background:#1565C0;color:white;border-radius:4px;padding:1px 6px;font-size:0.7rem;">📡 実データ</span>'
            if is_real else
            '<span style="background:#757575;color:white;border-radius:4px;padding:1px 6px;font-size:0.7rem;">📊 推定値</span>'
        )

        links = []
        if r.get("ebay_url"):
            links.append(f'<a href="{r["ebay_url"]}" target="_blank">📊 現在出品</a>')
        links.append(f'<a href="{sold_url}" target="_blank" style="color:#2E7D32;font-weight:bold;">✅ 落札済み確認</a>')
        if r.get("source_url"):
            links.append(f'<a href="{r["source_url"]}" target="_blank">🛒 {r.get("buy_source","仕入れ先")}</a>')
        link_html = " &nbsp;|&nbsp; ".join(links)

        st.markdown(f"""
        <div class="card {col_cls}">
          {badge} &nbsp; {data_badge}
          <div class="card-title">#{i+1} &nbsp;{r['keyword']}</div>
          <div class="card-genre">📁 {r['genre']} &nbsp;·&nbsp; 仕入れ: {r.get('buy_source','─')}</div>
          <div class="metric-row">
            <span class="metric-chip">💵 eBay ${r['avg_sold_usd']}</span>
            <span class="metric-chip {'ok' if r['sold_count'] >= 5 else 'bad'}">{'✅ 落札実績' if r.get('data_source')=='sold_real' else '📦 JP出品'} {r['sold_count']}件</span>
            <span class="metric-chip {'ok' if r.get('sell_through',0) >= 20 else 'bad'}">📈 売れ率 {r.get('sell_through',0)}%</span>
            <span class="metric-chip {'ok' if r['competition'] <= 100 else 'bad'}">👥 競合 {r['competition']}件</span>
          </div>
          <div class="metric-row">
            <span class="metric-chip">🏪 仕入れ ¥{r['buy_price']:,}</span>
            <span class="metric-chip {'ok' if r['profit_rate'] >= 30 else 'bad'}">📊 利益率 {r['profit_rate']}%</span>
            <span class="profit-big{profit_cls}">¥{r['profit']:,}</span>
          </div>
          <div style="font-size:0.82rem; margin-top:4px;">{link_html}</div>
        </div>
        """, unsafe_allow_html=True)

def render_genre_cards(data: dict):
    if not data: return
    for genre, items in data.items():
        ok = sum(1 for r in items if r.get("meets_all"))
        icon = "🟢" if ok > 0 else "🟡"
        with st.expander(f"{icon} {genre}　（全条件達成: {ok}件）", expanded=False):
            render_cards(items)

# ── メイン ────────────────────────────────────────────────
st.markdown("## 📦 Harbinger eBay リサーチ")

stocked, dropship, updated_at = load_cache()
expired = is_expired(updated_at)

# ステータスバー
if updated_at:
    age = (datetime.now() - updated_at).days
    st.caption(f"{'⚠️' if expired else '✅'} 最終更新: {updated_at.strftime('%m/%d %H:%M')}　（{age}日前）")
else:
    st.caption("⚠️ データなし。下のボタンでリサーチを実行してください")

# ── リサーチ実行ボタン ────────────────────────────────────
col1, col2 = st.columns(2)
with col1:
    if st.button("🏪 有在庫リサーチ", type="primary"):
        st.session_state["run_mode"] = "stocked"
        st.rerun()
with col2:
    if st.button("📦 無在庫リサーチ", type="primary"):
        st.session_state["run_mode"] = "dropship"
        st.rerun()

if st.button("🔄 両方まとめて実行"):
    st.session_state["run_mode"] = "both"
    st.rerun()

# ── 実行処理 ─────────────────────────────────────────────
mode = st.session_state.pop("run_mode", None)
if mode:
    if mode in ("stocked", "both"):
        with st.spinner("🔍 有在庫ジャンルをリサーチ中..."):
            stocked = research_stocked()
    if mode in ("dropship", "both"):
        with st.spinner("🔍 無在庫ジャンルをリサーチ中..."):
            dropship = research_dropship()
    save_cache(stocked or {}, dropship or {})
    st.success("✅ リサーチ完了！")
    st.rerun()

st.divider()

# ── タブ表示 ─────────────────────────────────────────────
tab1, tab2 = st.tabs(["🏪 有在庫", "📦 無在庫"])

with tab1:
    if stocked:
        all_s = [r for items in stocked.values() for r in items]
        c1, c2, c3 = st.columns(3)
        c1.metric("🟢 全条件達成", f"{sum(1 for r in all_s if r.get('meets_all'))}/{len(all_s)}")
        c2.metric("平均利益率",   f"{sum(r['profit_rate'] for r in all_s)/len(all_s):.1f}%")
        c3.metric("平均売れ率",   f"{sum(r.get('sell_through',0) for r in all_s)/len(all_s):.1f}%")
        st.caption("仕入れ先：ヤフオク・エコリング・ハードオフ・駿河屋・Amazon")
        render_genre_cards(stocked)
        df = pd.DataFrame(all_s)
        st.download_button("📥 CSV保存", df.to_csv(index=False, encoding="utf-8-sig"),
                           f"stocked_{datetime.now().strftime('%Y%m%d')}.csv", "text/csv")
    else:
        st.info("👆 「有在庫リサーチ」ボタンを押してください")

with tab2:
    if dropship:
        all_d = [r for items in dropship.values() for r in items]
        c1, c2, c3 = st.columns(3)
        c1.metric("🟢 全条件達成", f"{sum(1 for r in all_d if r.get('meets_all'))}/{len(all_d)}")
        c2.metric("平均利益率",   f"{sum(r['profit_rate'] for r in all_d)/len(all_d):.1f}%")
        c3.metric("平均売れ率",   f"{sum(r.get('sell_through',0) for r in all_d)/len(all_d):.1f}%")
        st.caption("仕入れ先：Amazon・キタムラ・ヨドバシ（注文後に仕入れ）")
        render_genre_cards(dropship)
        df = pd.DataFrame(all_d)
        st.download_button("📥 CSV保存", df.to_csv(index=False, encoding="utf-8-sig"),
                           f"dropship_{datetime.now().strftime('%Y%m%d')}.csv", "text/csv")
    else:
        st.info("👆 「無在庫リサーチ」ボタンを押してください")

# ── 利益計算機 ───────────────────────────────────────────
st.divider()
with st.expander("💰 利益計算機（手動）"):
    st.caption("気になる商品をその場で計算")
    buy = st.number_input("仕入れ価格（円）", value=3000, step=500)
    sell = st.number_input("eBay売値（USD）", value=50.0, step=5.0)
    ship = st.number_input("国際送料（円）", value=3750, step=100)

    rate_res = None
    try:
        import requests as _r
        rate_res = _r.get("https://open.er-api.com/v6/latest/USD", timeout=3).json()["rates"]["JPY"]
    except Exception:
        rate_res = 150.0

    gross = sell * rate_res
    fees  = gross * (0.1325 + 0.029 + 0.015 + 0.03)
    net   = gross - fees
    profit = net - buy - ship - 300
    rate  = (profit / (buy + ship + 300)) * 100 if (buy + ship + 300) > 0 else 0

    col_a, col_b = st.columns(2)
    col_a.metric("純利益", f"¥{int(profit):,}")
    col_b.metric("利益率", f"{rate:.1f}%", delta="目標30%" if rate >= 30 else "要改善")
    st.caption(f"為替レート: 1USD = {rate_res:.1f}円　eBay手数料13.25%・決済2.9%・為替1.5%・返品リスク3%込み")
