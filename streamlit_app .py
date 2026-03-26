# -*- coding: utf-8 -*-
import requests
import pandas as pd
import datetime as dt
import time
import sqlite3
import getpass
from bs4 import BeautifulSoup
from dateutil.relativedelta import relativedelta
from datetime import datetime

# 第三方套件 (請確保環境已安裝: pip install yfinance FinMind finlab selenium)
try:
    import yfinance as yf
    from FinMind.data import DataLoader
    import finlab
    from finlab import data as finlab_data
    from selenium import webdriver
except ImportError as e:
    print(f"缺少套件，請執行 pip install 安裝: {e}")

# ==========================================
# 1. 證交所資料爬蟲模組
# ==========================================

def get_twse_stock_day(stock_id, date_str):
    """取得證交所個股日成交資訊"""
    url = f'https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={date_str}&stockNo={stock_id}'
    try:
        response = requests.get(url)
        json_data = response.json()
        if json_data.get('stat') == 'OK':
            return pd.DataFrame(data=json_data['data'], columns=json_data['fields'])
        return pd.DataFrame()
    except Exception as e:
        print(f"證交所連線失敗: {e}")
        return pd.DataFrame()

def get_twse_bwibbu_history(stock_id, month_num=3):
    """取得連續月份個股本益比資料"""
    date_now = dt.datetime.now()
    date_list = [(date_now - relativedelta(months=i)).replace(day=1).strftime('%Y%m%d') 
                 for i in range(month_num)]
    date_list.reverse()
    
    all_df = pd.DataFrame()
    for date in date_list:
        url = f'https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU?date={date}&stockNo={stock_id}'
        try:
            json_data = requests.get(url).json()
            if 'data' in json_data:
                df = pd.DataFrame(data=json_data['data'], columns=json_data['fields'])
                all_df = pd.concat([all_df, df], ignore_index=True)
            time.sleep(2) # 避免請求過快被封鎖
        except Exception:
            print(f"無法取得 {date} 的資料")
    return all_df

# ==========================================
# 2. Yahoo 股市爬蟲模組
# ==========================================

def get_yahoo_stock_realtime(stock_id):
    """取得 Yahoo 股市當日即時股價"""
    url = f'https://tw.stock.yahoo.com/quote/{stock_id}.TW'
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.content, 'html.parser')
    info_section = soup.find('section', {'id': 'qsp-overview-realtime-info'})
    
    if not info_section:
        return "找不到即時行情區塊"

    time_element = info_section.find('time')
    trade_time = time_element.text if time_element else "未知"

    fields, datas = [], []
    for item in info_section.find_all('li'):
        spans = item.find_all('span')
        if len(spans) >= 2:
            field_name = spans[0].text.strip()
            data_value = spans[1].text.strip()
            if field_name:
                fields.append(field_name)
                datas.append(data_value)

    df = pd.DataFrame([datas], columns=fields)
    df.insert(0, '日期', trade_time)
    df.insert(1, '股號', stock_id)
    return df

def get_yahoo_financial_statement(stock_id, statement_type='income-statement'):
    """取得 Yahoo 股市季報表 (損益表、資產負債表等)"""
    url = f'https://tw.stock.yahoo.com/quote/{stock_id}/{statement_type}'
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.content, 'html.parser')
    section_id = f'qsp-{statement_type}-table'
    table_soup = soup.find('section', {'id': section_id})

    if not table_soup:
        return None

    # 解析表頭與資料
    header = [s.strip() for s in table_soup.find('div', class_='table-header').stripped_strings]
    data_rows = [list(row.stripped_strings) for row in table_soup.find_all('li', class_='List(n)')]

    raw_df = pd.DataFrame(data_rows, columns=header)
    # 資料轉置處理
    df = raw_df.transpose()
    df.columns = df.iloc[0]
    df = df[1:].copy()
    df.insert(0, '年度/季別', df.index)
    df.reset_index(drop=True, inplace=True)
    return df

# ==========================================
# 3. 鉅亨網新聞爬蟲 (替代 Selenium)
# ==========================================

def get_cnyes_news(stock_id, limit=20):
    """取得鉅亨網股票新聞內文"""
    field = ['股號','日期','標題','內容']
    data_list = []
    api_url = f'https://ess.api.cnyes.com/ess/api/v1/news/keyword?q={stock_id}&limit={limit}&page=1'
    
    try:
        json_data = requests.get(api_url).json()
        items = json_data['data']['items']
        for item in items:
            news_id = item["newsId"]
            title = item["title"]
            formatted_date = datetime.fromtimestamp(item["publishAt"]).strftime('%Y/%m/%d')
            
            # 抓取新聞內文
            news_url = f'https://news.cnyes.com/news/id/{news_id}'
            news_soup = BeautifulSoup(requests.get(news_url).content, 'html.parser')
            p_text = "".join([p.get_text() for p in news_soup.find_all('p')[4:]])
            
            data_list.append([stock_id, formatted_date, title, p_text])
    except Exception as e:
        print(f"新聞抓取發生錯誤: {e}")
        
    return pd.DataFrame(data_list, columns=field)

# ==========================================
# 4. SQL 資料庫操作模組
# ==========================================

class StockDB:
    def __init__(self, db_name='stock.db'):
        self.conn = sqlite3.connect(db_name)
        self.create_table()

    def create_table(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS 日頻資料 (
                sno INTEGER PRIMARY KEY AUTOINCREMENT,
                Stock_Id TEXT,
                Date DATE,
                Open FLOAT, High FLOAT, Low FLOAT, Close FLOAT,
                Adj_Close FLOAT, Volume INTEGER
            );
        ''')
        self.conn.commit()

    def insert_yf_data(self, stock_id, start_date):
        """下載 yfinance 資料並存入 DB"""
        symbol = f"{stock_id}.TW"
        df = yf.download(symbol, start=start_date, auto_adjust=False, multi_level_index=False)
        df = df.reset_index()
        df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')
        df.rename(columns={"Adj Close": "Adj_Close"}, inplace=True)
        df.insert(0, 'Stock_Id', str(stock_id))
        
        df.to_sql('日頻資料', self.conn, if_exists='append', index=False)
        print(f"{stock_id} 資料已匯入資料庫")

    def query_data(self, sql_query):
        return pd.read_sql(sql_query, self.conn)

    def close(self):
        self.conn.close()

# ==========================================
# 5. 主程式執行範例
# ==========================================

if __name__ == "__main__":
    target_id = '2330'
    
    # 測試 Yahoo 即時股價
    print(f"--- 正在獲取 {target_id} 即時行情 ---")
    print(get_yahoo_stock_realtime(target_id))

    # 測試新聞抓取
    print(f"\n--- 正在獲取 {target_id} 相關新聞 ---")
    news_df = get_cnyes_news(target_id, limit=5)
    print(news_df[['日期', '標題']].head())

    # 測試資料庫操作
    # db = StockDB()
    # db.insert_yf_data('2317', '2023-08-01')
    # print(db.query_data("SELECT * FROM 日頻資料 LIMIT 5"))
    # db.close()

    print("\n程式執行完畢！")
