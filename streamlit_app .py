import streamlit as st
import pandas as pd
import requests
import yfinance as yf
import datetime as dt
from bs4 import BeautifulSoup
from datetime import datetime

# --- 網頁頁面配置 ---
st.set_page_config(page_title="台股分析網頁", layout="wide")
st.title("📈 台股自動化查詢系統")

# --- 使用者輸入框 (放在側邊欄) ---
with st.sidebar:
    st.header("查詢設定")
    stock_id = st.text_input("請輸入台股代號 (如: 2330)", value="2330")
    st.write("---")
    st.caption("此網頁整合了證交所、Yahoo、鉅亨網與 yfinance 資料。")

# --- 定義功能函式 (這就是把你原本 Colab 的 logic 封裝起來) ---

def get_yahoo_data(sid):
    """對應你 Colab 第 5 步：Yahoo 股價"""
    url = f'https://tw.stock.yahoo.com/quote/{sid}.TW'
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.content, 'html.parser')
    info_section = soup.find('section', {'id': 'qsp-overview-realtime-info'})
    if not info_section: return None
    fields, datas = [], []
    for item in info_section.find_all('li'):
        spans = item.find_all('span')
        if len(spans) >= 2:
            fields.append(spans[0].text.strip())
            datas.append(spans[1].text.strip())
    return pd.DataFrame([datas], columns=fields)

def get_cnyes_news(sid):
    """對應你 Colab 第 7 步：鉅亨網新聞"""
    url = f'https://ess.api.cnyes.com/ess/api/v1/news/keyword?q={sid}&limit=10&page=1'
    json_data = requests.get(url).json()
    items = json_data['data']['items']
    data = []
    for item in items:
        pub_date = datetime.fromtimestamp(item["publishAt"]).strftime('%Y-%m-%d')
        data.append({"日期": pub_date, "標題": item["title"], "連結": f'https://news.cnyes.com/news/id/{item["newsId"]}'})
    return pd.DataFrame(data)

# --- 按鈕觸發區 ---
if st.button("🚀 開始查詢股市資料"):
    
    with st.spinner(f"正在抓取 {stock_id} 的最新資訊..."):
        # 分成三個頁籤顯示
        tab1, tab2, tab3 = st.tabs(["📊 歷史圖表", "📋 即時數據", "📰 相關新聞"])

        with tab1:
            st.subheader("yfinance 股價走勢")
            # 對應你 Colab 第 12 步
            target = f"{stock_id}.TW"
            df_yf = yf.download(target, period="6mo")
            if not df_yf.empty:
                st.line_chart(df_yf['Close'])
                st.dataframe(df_yf.tail(10), use_container_width=True)
            else:
                st.error("找不到該股票的歷史資料。")

        with tab2:
            st.subheader("Yahoo 股市即時概況")
            df_yahoo = get_yahoo_data(stock_id)
            if df_yahoo is not None:
                st.table(df_yahoo.T) # 轉置一下比較好讀
            else:
                st.warning("Yahoo 資料抓取失敗")

        with tab3:
            st.subheader("鉅亨網最新相關新聞")
            df_news = get_cnyes_news(stock_id)
            if not df_news.empty:
                # 用簡單的列表顯示新聞
                for i, row in df_news.iterrows():
                    st.markdown(f"📍 **[{row['日期']}]** [{row['標題']}]({row['連結']})")
            else:
                st.write("目前查無相關新聞。")

    st.success("🎉 查詢完成！")
else:
    st.info("請在左側輸入股票代碼，然後按下上面的按鈕開始查詢。")
