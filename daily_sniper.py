import requests
import yfinance as yf
import pandas as pd
import datetime
import time

# ==========================================
# 1. 設定區 (已替換為您的 n8n Production URL)
# ==========================================
WEBHOOK_URL = "https://james15211521.zeabur.app/webhook/9c373521-2ad5-4b49-af47-0de94910867c"

def get_latest_twse_chips():
    """加上 Headers 偽裝成瀏覽器，並嚴格對齊台灣時區"""
    print("🔄 正在取得上市法人籌碼資料...")
    
    # 防護一：強制使用台灣時區 (UTC+8)
    tw_tz = datetime.timezone(datetime.timedelta(hours=8))
    now_tw = datetime.datetime.now(tw_tz)
    
    # 防護二：偽裝成正常瀏覽器
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36"
    }
    
    for i in range(7):
        d = now_tw - datetime.timedelta(days=i)
        if d.weekday() >= 5: continue 
        
        date_str = d.strftime("%Y%m%d")
        url = f"https://www.twse.com.tw/fund/T86?response=json&date={date_str}&selectType=ALL"
        
        try:
            res = requests.get(url, headers=headers, timeout=10).json()
            if res.get('stat') == 'OK' and res.get('data'):
                print(f"✅ 成功取得 {date_str} 籌碼資料！")
                return date_str, res['data'] 
        except Exception as e:
            print(f"⚠️ 嘗試 {date_str} 發生連線錯誤，自動退回前一日...")
            pass
        time.sleep(1.5)
    return None, None

def main():
    chip_date, raw_data = get_latest_twse_chips()
    if not raw_data:
        print("❌ 無法取得近期籌碼資料。")
        return
        
    target_stocks = {}
    for row in raw_data:
        sid, name = row[0].strip(), row[1].strip()
        if len(sid) != 4: continue 
        
        f_lots = int(row[4].replace(',', '')) // 1000 if row[4] else 0
        t_lots = int(row[10].replace(',', '')) // 1000 if row[10] else 0
        
        if f_lots > 0 or t_lots > 0:
            target_stocks[sid] = {
                "name": name,
                "chip_text": f"外資買 {f_lots} 張, 投信買 {t_lots} 張"
            }
            
    print(f"📊 籌碼初篩完成，開始下載近15日量價進行策略運算 (基準日: {chip_date})...")
    
    tickers = [f"{sid}.TW" for sid in target_stocks.keys()]
    
    # ⭐️ 修正 2：加入 threads=False 防止 yfinance 在 GitHub 上卡死
    hist_data = yf.download(tickers, period="15d", group_by='ticker', progress=False, threads=False)
    
    golden_list = []
    
    target_iso_date = f"{chip_date[:4]}-{chip_date[4:6]}-{chip_date[6:]}"
    
    for sid, info in target_stocks.items():
        ticker = f"{sid}.TW"
        if ticker not in hist_data: continue
        
        df = hist_data[ticker].dropna()
        df = df[:target_iso_date].copy()
        
        if len(df) < 6: continue
        
        # ⭐️ 修正 1：必須先算均線，再抽取 latest，否則會 KeyError
        df['Vol_MA5'] = df['Volume'].rolling(5).mean()
        latest = df.iloc[-1]
        
        # 再次驗證：確保 K 線的最後一筆，真的是我們抓到籌碼的那一天
        if latest.name.strftime('%Y%m%d') != chip_date:
            continue 
        
        vol_ma5 = latest['Vol_MA5']
        open_p = latest['Open']
        close_p = latest['Close']
        vol = latest['Volume']
        
        if open_p == 0 or vol_ma5 == 0: continue
        
        k_body = close_p / open_p
        vol_ratio = vol / vol_ma5
        
        cond_red_k = k_body > 1.04           
        cond_vol = 1.2 <= vol_ratio <= 2.5   
        
        if cond_red_k and cond_vol:
            golden_list.append({
                "stock_id": sid,
                "stock_name": info["name"],
                "chip_info": info["chip_text"]
            })
            print(f"🎯 鎖定目標: {sid} {info['name']} (漲幅: {(k_body-1)*100:.1f}%, 量比: {vol_ratio:.1f}倍)")

    if not golden_list:
        print(f"🔍 {chip_date} 無符合大紅K與溫和放量策略的標的。")
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
