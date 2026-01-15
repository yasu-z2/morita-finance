# ==========================================================
# プログラム名: 株価選別・AI分析システム
# バージョン: 3.5.2 (Gemini 2.5 Flash 固定・厳守事項反映版)
# ==========================================================

import os
import yfinance as yf
import pandas as pd
import time
import smtplib
import pickle
from google import genai
from dotenv import load_dotenv
from email.mime.text import MIMEText
from email.utils import formatdate
from datetime import datetime, timedelta, timezone
from tqdm import tqdm

# --- 1. 初期設定 ---
load_dotenv()

# v1.11 アルゴリズム固定定数
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

# --- 2. AI分析関数 (Gemini 2.5 Flash 固定) ---
def call_gemini(prompt):
    if not GEMINI_API_KEY:
        return "AI分析を実行できませんでした。APIキーが設定されていません。"
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        # ご指定の最新安定版モデルに固定
        response = client.models.generate_content(
            model="gemini-2.5-flash", 
            contents=prompt
        )
        return response.text
    except Exception as e:
        return f"AI分析を実行できませんでした。エラー詳細: {e}"

# --- 3. メール送信関数 ---
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
    except Exception as e:
        print(f"送信エラー: {e}")

# --- 4. メイン処理 (v1.11ロジック固定) ---
def run_scanner_final():
    jpx_csv = 'data_jpx.csv'
    if not os.path.exists(jpx_csv):
        print(f"エラー: {jpx_csv} が見つかりません。")
        return

    df_full = pd.read_csv(jpx_csv, encoding='cp932')
    condition = df_full['市場・商品区分'].str.contains('プライム') & df_full['市場・商品区分'].str.contains('内国株式')
    df_prime = df_full[condition].copy()
    df_prime['コード'] = df_prime['コード'].astype(str).str.strip()
    name_map = dict(zip(df_prime['コード'], df_prime['銘柄名']))
    codes = [f"{c}.T" for c in name_map.keys()]

    stock_data_cache = {}
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'rb') as f: stock_data_cache = pickle.load(f)
        except: pass

    stage1_list = []
    stage2_list = []

    print(f"スキャン開始 ({len(codes)}銘柄対象)...")

    for code in tqdm(codes):
        try:
            df = None
            if code in stock_data_cache:
                last_df, last_time = stock_data_cache[code]
                if (datetime.now() - last_time).seconds < 3600:
                    df = last_df

            if df is None:
                time.sleep(REQUEST_SLEEP)
                df = yf.Ticker(code).history(period=HISTORY_PERIOD)
                if not df.empty:
                    stock_data_cache[code] = (df, datetime.now())

            if len(df) < (WINDOW_DAYS + 1): continue

            df_window = df.iloc[-WINDOW_DAYS:]
            low_window = df_window['Low'].min()
            current_price = df_window['Close'].iloc[-1]
            vol_avg = df_window['Volume'].mean()
            vol_today = df_window['Volume'].iloc[-1]
            vol_yesterday = df_window['Volume'].iloc[-2]

            # v1.11 判定
            is_range_s1 = df_window['Close'].iloc[:-3].max() <= (low_window * RANGE_FACTOR_S1)
            up_from_low = current_price >= (low_window * UP_FROM_LOW_RATE)
            high_vol_s1 = (vol_today >= vol_avg * VOL_MULT_S1_TODAY) and (vol_yesterday >= vol_avg * VOL_MULT_S1_YEST)

            if is_range_s1 and up_from_low and high_vol_s1 and ((current_price * 100) <= PRICE_LIMIT_YEN):
                target1 = max(current_price * 0.97, df_window['Open'].iloc[-1])
                target2 = (low_window + current_price) / 2
                stop_loss = df['Close'].iloc[-5:].mean()
                
                pure_code = code.replace('.T','')
                item = {
                    "コード": pure_code, "名称": name_map.get(pure_code, 'N/A'), "終値": round(current_price, 1),
                    "上昇率": f"{round(((current_price/low_window)-1)*100, 1)}%",
                    "第1指値": round(target1, 1), "第2指値": round(target2, 1),
                    "損切目安": round(stop_loss, 1), "出来高倍": round(vol_today/vol_avg, 1)
                }

                is_range_s2 = df_window['Close'].iloc[:-1].max() <= (low_window * RANGE_FACTOR_S2)
                high_vol_s2 = (vol_today >= vol_avg * VOL_MULT_S2) and (vol_yesterday >= vol_avg * VOL_MULT_S2)
                if is_range_s2 and high_vol_s2:
                    stage2_list.append(item)
                
                stage1_list.append(item)
        except: continue

    with open(CACHE_FILE, 'wb') as f: pickle.dump(stock_data_cache, f)

    # --- レポート作成 ---
    now_jst = datetime.now(JST)
    subject = f"【AI株式分析】本日のスクリーニングレポート該当{len(stage1_list)}件"
    body = f"■ 実行日時(JST): {now_jst.strftime('%Y/%m/%d %H:%M')}\n\n"

    # 第一段階
    body += "▼▼ 【第一段階：実戦モード】 注目候補 ▼▼\n"
    body += "・底値圏: 過去25日安値から +15%以内\n"
    body += "・初動: 当日終値が安値から +10%以上 上昇\n"
    body += "・出来高: 当日2.0倍、前日1.5倍以上の急増\n"
    body += "-" * 50 + "\n"
    if not stage1_list:
        body += "該当なし\n\n"
    else:
        for res in stage1_list:
            body += f"■ {res['名称']} ({res['コード']}.T)\n"
            body += f"   終値: {res['終値']}円 (安値比 {res['上昇率']})\n"
            body += f"   指値: [浅め] {res['第1指値']}円 / [本命] {res['第2指値']}円\n"
            body += f"   損切: {res['損切目安']}円以下\n"
            body += f"   Yahoo: https://finance.yahoo.co.jp/quote/{res['コード']}.T\n"
            body += "-" * 40 + "\n"

    # 第二段階
    body += "\n▼▼ 【第二段階：厳格モード】 特選初動候補 ▼▼\n"
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
            body += f"  Yahoo: https://finance.yahoo.co.jp/quote/{res['コード']}.T\n\n"

    # AI分析
    prompt = f"以下の銘柄リストは底値圏からの初動候補です。背景を考慮し詳細に分析して：\n{stage1_list}"
    body += f"\n【AIによる市場概況・分析】\n{call_gemini(prompt)}"

    send_report_email(subject, body)
    print("完了しました。")

if __name__ == '__main__':
    run_scanner_final()