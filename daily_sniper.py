import requests
import yfinance as yf
import pandas as pd
import datetime
import time

# ==========================================
# 1. 設定區 (請將下方網址替換為您 n8n Webhook 的 Test URL)
# ==========================================
WEBHOOK_URL = "https://james15211521.zeabur.app/webhook-test/9c373521-2ad5-4b49-af47-0de94910867c"

def get_latest_twse_chips():
    """自動往回尋找最近一個交易日的證交所法人買賣超資料"""
    print("🔄 正在取得上市法人籌碼資料...")
    for i in range(7):
        d = datetime.datetime.now() - datetime.timedelta(days=i)
        if d.weekday() >= 5: continue # 跳過週末
        
        date_str = d.strftime("%Y%m%d")
        url = f"https://www.twse.com.tw/fund/T86?response=json&date={date_str}&selectType=ALL"
        
        try:
            res = requests.get(url, timeout=10).json()
            if res.get('stat') == 'OK' and res.get('data'):
                print(f"✅ 成功取得 {date_str} 籌碼資料！")
                return res['data']
        except Exception as e:
            continue
        time.sleep(1)
    return None

def main():
    raw_data = get_latest_twse_chips()
    if not raw_data:
        print("❌ 無法取得近期籌碼資料。")
        return
        
    # 2. 初步籌碼過濾：只挑選「外資或投信有買超」的普通股
    target_stocks = {}
    for row in raw_data:
        sid, name = row[0].strip(), row[1].strip()
        if len(sid) != 4: continue # 只抓四碼一般股票
        
        # 證交所外資欄位(idx 4), 投信欄位(idx 10)
        f_lots = int(row[4].replace(',', '')) // 1000 if row[4] else 0
        t_lots = int(row[10].replace(',', '')) // 1000 if row[10] else 0
        
        if f_lots > 0 or t_lots > 0:
            target_stocks[sid] = {
                "name": name,
                "chip_text": f"外資買 {f_lots} 張, 投信買 {t_lots} 張"
            }
            
    print(f"📊 籌碼初篩完成，共有 {len(target_stocks)} 檔獲法人買進。開始下載近10日量價進行策略運算...")
    
    # 3. 透過 yfinance 快速下載這幾百檔股票的近 10 日 K 線
    tickers = [f"{sid}.TW" for sid in target_stocks.keys()]
    # yfinance 批次下載速度極快
    hist_data = yf.download(tickers, period="10d", group_by='ticker', progress=False)
    
    golden_list = []
    
    # 4. 執行黃金策略：實體大紅K (>4%) + 溫和放量 (1.2~2.5倍)
    for sid, info in target_stocks.items():
        ticker = f"{sid}.TW"
        if ticker not in hist_data: continue
        
        df = hist_data[ticker].dropna()
        if len(df) < 6: continue # 資料不足無法計算 5 日均量
        
        # 計算 5 日均量
        df['Vol_MA5'] = df['Volume'].rolling(5).mean()
        
        latest = df.iloc[-1] # 取最新一個交易日
        open_p = latest['Open']
        close_p = latest['Close']
        vol = latest['Volume']
        vol_ma5 = latest['Vol_MA5']
        
        if open_p == 0 or vol_ma5 == 0: continue
        
        k_body = close_p / open_p
        vol_ratio = vol / vol_ma5
        
        # 💥 策略核心條件判斷 💥
        cond_red_k = k_body > 1.04           # 實體大紅K
        cond_vol = 1.2 <= vol_ratio <= 2.5   # 溫和放量，避開極端爆量引發隔日沖
        
        if cond_red_k and cond_vol:
            golden_list.append({
                "stock_id": sid,
                "stock_name": info["name"],
                "chip_info": info["chip_text"]
            })
            print(f"🎯 鎖定目標: {sid} {info['name']} (漲幅: {(k_body-1)*100:.1f}%, 量比: {vol_ratio:.1f}倍)")

    # 5. 將結果發送給 n8n
    if not golden_list:
        print("🔍 今日無符合大紅K與溫和放量策略的標的。")
    else:
        print(f"\n🚀 準備將 {len(golden_list)} 檔精選標的發送至 n8n...")
        try:
            res = requests.post(WEBHOOK_URL, json={"data": golden_list})
            if res.status_code == 200:
                print("✅ 成功發送至 n8n！請檢查 Telegram 接收 AI 報告。")
            else:
                print(f"⚠️ 發送失敗，狀態碼: {res.status_code}")
        except Exception as e:
            print(f"⚠️ 發送至 Webhook 發生錯誤: {e}")

if __name__ == "__main__":
    main()