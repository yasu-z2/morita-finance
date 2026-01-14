# ==========================================================
# プログラム名: 株価選別・AI分析システム
# バージョン: 3.3.7 (v1.11 ロジック・計算式・タイトル完全同期)
# ==========================================================

import os
import yfinance as yf
import pandas as pd
import time
import smtplib
import pickle
import google.generativeai as genai
from email.mime.text import MIMEText
from email.utils import formatdate
from datetime import datetime, timedelta, timezone
from tqdm import tqdm

# --- 設定定数 (v1.11 ソースコードより厳密に転記) ---
HISTORY_PERIOD = '40d'
WINDOW_DAYS = 25
RANGE_FACTOR_S1 = 1.15
RANGE_FACTOR_S2 = 1.10
UP_FROM_LOW_RATE = 1.10
VOL_MULT_S1_TODAY = 2.0
VOL_MULT_S1_YEST = 1.5
VOL_MULT_S2 = 2.0
PRICE_LIMIT_YEN = 200000
REQUEST_SLEEP = 0.1
CACHE_FILE = 'stock_cache.pkl'

# 環境変数・JST
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
MAIL_ADDRESS   = os.environ.get('MAIL_ADDRESS')
MAIL_PASSWORD  = os.environ.get('MAIL_PASSWORD')
TO_ADDRESS     = os.environ.get('TO_ADDRESS')
JST = timezone(timedelta(hours=+9), 'JST')

def call_gemini(prompt):
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-2.0-flash") # 安定版
        return model.generate_content(prompt).text
    except: return "AI分析を実行できませんでした。"

def send_report_email(subject, body):
    if not TO_ADDRESS: return
    recipient_list = [addr.strip() for addr in TO_ADDRESS.split(',')]
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = MAIL_ADDRESS
    msg['To'] = ", ".join(recipient_list)
    msg['Date'] = formatdate(localtime=True)
    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(MAIL_ADDRESS, MAIL_PASSWORD)
        server.send_message(msg, to_addrs=recipient_list)
        server.close()
    except Exception as e: print(f"送信エラー: {e}")

def run_scanner_final():
    jpx_csv = 'data_jpx.csv'
    df_full = pd.read_csv(jpx_csv, encoding='cp932')
    # v1.11の内国株式条件も追加
    condition = df_full['市場・商品区分'].str.contains('プライム') & df_full['市場・商品区分'].str.contains('内国株式')
    df_prime = df_full[condition].copy()
    name_map = dict(zip(df_prime['コード'].astype(str), df_prime['銘柄名']))
    codes = [f"{str(c).strip()}.T" for c in df_prime['コード']]

    stock_data_cache = {}
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'rb') as f: stock_data_cache = pickle.load(f)
        except: pass

    stage1_list = []
    stage2_list = []

    print(f"--- v1.11準拠スキャン開始 ({len(codes)}銘柄) ---")

    for code in tqdm(codes):
        try:
            df = None
            if code in stock_data_cache:
                last_df, last_time = stock_data_cache[code]
                if (datetime.now() - last_time).days < 1: df = last_df

            if df is None:
                time.sleep(REQUEST_SLEEP)
                df = yf.Ticker(code).history(period=HISTORY_PERIOD)
                stock_data_cache[code] = (df, datetime.now())

            if len(df) < (WINDOW_DAYS + 1): continue

            # --- v1.11 判定ロジック完全転記 ---
            df_window = df.iloc[-WINDOW_DAYS:]
            low_window = df_window['Low'].min()
            current_price = df_window['Close'].iloc[-1]
            vol_avg = df_window['Volume'].mean() # 当日込み平均
            vol_today = df_window['Volume'].iloc[-1]
            vol_yesterday = df_window['Volume'].iloc[-2]

            # 1. 底値圏での停滞 (直近3日を除外)
            is_range_s1 = df_window['Close'].iloc[:-3].max() <= (low_window * RANGE_FACTOR_S1)
            # 2. 初動の跳ね上がり
            up_from_low = current_price >= (low_window * UP_FROM_LOW_RATE)
            # 3. 出来高の急増
            high_vol_s1 = (vol_today >= vol_avg * VOL_MULT_S1_TODAY) and (vol_yesterday >= vol_avg * VOL_MULT_S1_YEST)

            # 総合判定 & 予算制限
            if is_range_s1 and up_from_low and high_vol_s1 and ((current_price * 100) <= PRICE_LIMIT_YEN):
                # 指値・損切計算 (v1.11計算式)
                target1 = max(current_price * 0.97, df_window['Open'].iloc[-1])
                target2 = (low_window + current_price) / 2
                stop_loss = df['Close'].iloc[-5:].mean()
                
                pure_code = code.replace('.T','')
                item = {
                    "コード": pure_code, "名称": name_map.get(pure_code, 'N/A'), "終値": round(current_price, 1),
                    "上昇率": f"{round(((current_price/low_window)-1)*100, 1)}%",
                    "第1指値": round(target1, 1), "第2指値": round(target2, 1),
                    "損切目安": round(stop_loss, 1), "出来高倍": round(vol_today/vol_avg, 1),
                    "URL_Y": f"https://finance.yahoo.co.jp/quote/{code}",
                    "URL_K": f"https://kabutan.jp/stock/chart?code={pure_code}"
                }

                # 第二段階の判定 (v1.11準拠)
                is_range_s2 = df_window['Close'].iloc[:-1].max() <= (low_window * RANGE_FACTOR_S2)
                high_vol_s2 = (vol_today >= vol_avg * VOL_MULT_S2) and (vol_yesterday >= vol_avg * VOL_MULT_S2)
                
                if is_range_s2 and high_vol_s2:
                    stage2_list.append(item)
                
                stage1_list.append(item)
        except: continue

    with open(CACHE_FILE, 'wb') as f: pickle.dump(stock_data_cache, f)

    # --- レポート作成 ---
    now_jst = datetime.now(JST)
    subject = f"【AI分析】本日のスクリーニングレポート該当{len(stage1_list)}件"
    
    body = f"■ 実行日時(JST): {now_jst.strftime('%Y/%m/%d %H:%M')}\n\n"

    body += "▼▼ 【第二段階：厳格モード】 特選初動候補 ▼▼\n"
    body += "※注目候補の中からさらに厳選\n"
    body += "・底値圏: 安値から +10%以内\n"
    body += "・出来高: 2日連続で2.0倍以上 の急増を記録した最有力候補\n"
    body += "-" * 50 + "\n"
    if not stage2_list:
        body += "該当なし\n\n"
    else:
        for res in stage2_list:
            body += f"★特選銘柄: {res['名称']} ({res['コード']}.T)\n"
            body += f"  価格: {res['終値']}円 / 指値1: {res['第1指値']}円 / 指値2: {res['第2指値']}円\n"
            body += f"  Yahoo: {res['URL_Y']}\n  株探 : {res['URL_K']}\n\n"

    body += "▼▼ 【第一段階：実戦モード】 注目候補 ▼▼\n"
    body += "・底値圏: 過去25日安値から +15%以内\n"
    body += "・初動: 当日終値が安値から +10%以上 上昇\n"
    body += "・出来高: 当日2.0倍、前日1.5倍以上の急増\n"
    body += "-" * 50 + "\n"
    if not stage1_list:
        body += "該当なし\n"
    else:
        for res in stage1_list:
            body += f"■ {res['名称']} ({res['コード']}.T)\n"
            body += f"   終値: {res['終値']}円 (安値比 {res['上昇率']})\n"
            body += f"   指値: [浅め] {res['第1指値']}円 / [本命] {res['第2指値']}円\n"
            body += f"   損切: {res['損切目安']}円以下\n"
            body += f"   Yahoo: {res['URL_Y']}\n   株探 : {res['URL_K']}\n"
            body += "-" * 40 + "\n"

    prompt = f"以下の銘柄リストは底値圏からの初動候補です。チャートと出来高の背景を考慮し、簡潔に分析して：\n{stage1_list}"
    body += f"\n\n【AIによる市場概況・分析】\n{call_gemini(prompt)}"

    send_report_email(subject, body)

if __name__ == '__main__':
    run_scanner_final()