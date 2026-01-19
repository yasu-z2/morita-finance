# ==========================================================
# プログラム名: 株価選別・AI分析システム
# バージョン: 3.7.2 (Gemini 2.5 Flash 固定・キャッシュロジック修正)
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

# --- 2. AI分析関数 (Gemini 2.5 Flash 固定 & リトライ) ---
def call_gemini_with_retry(prompt):
    if not GEMINI_API_KEY:
        return "AI分析を実行できませんでした。APIキーが設定されていません。"
    
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    for attempt in range(3):
        try:
            # モデルを gemini-2.5-flash に固定
            response = client.models.generate_content(
                model="gemini-2.5-flash", 
                contents=prompt
            )
            return response.text
        except Exception as e:
            err_msg = str(e).lower()
            if ("503" in err_msg or "overloaded" in err_msg) and attempt < 2:
                print(f"\n[AI] サーバー混雑中。15秒後に再試行します... ({attempt + 1}/3)")
                time.sleep(15)
                continue
            return f"AI分析を実行できませんでした。エラー詳細: {e}"

# --- 3. メイン処理 ---
def run_scanner_final():
    jpx_csv = 'data_jpx.csv'
    if not os.path.exists(jpx_csv):
        print(f"エラー: {jpx_csv} が見つかりません。")
        return

    try:
        df_full = pd.read_csv(jpx_csv, encoding='cp932')
    except:
        df_full = pd.read_csv(jpx_csv, encoding='utf-8')

    # 銘柄抽出（3.5.2のロジック維持）
    condition = df_full['市場・商品区分'].str.contains('プライム') & df_full['市場・商品区分'].str.contains('内国株式')
    df_prime = df_full[condition].copy()
    df_prime['コード'] = df_prime['コード'].astype(str).str.strip().str.replace('.0', '', regex=False)
    name_map = dict(zip(df_prime['コード'], df_prime['銘柄名']))
    codes = [f"{c}.T" for c in name_map.keys()]

    # キャッシュのロードと有効期限チェック
    stock_data_cache = {}
    valid_cache_count = 0
    now = datetime.now()

    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'rb') as f: 
                loaded_cache = pickle.load(f)
                # ファイル内の各銘柄のタイムスタンプをチェック
                for c, val in loaded_cache.items():
                    # val[1] が datetime オブジェクトであることを前提
                    if (now - val[1]).total_seconds() < 3600:
                        valid_cache_count += 1
                stock_data_cache = loaded_cache
        except Exception as e:
            print(f"キャッシュロード失敗: {e}")

    # 修正：正確な状況表示
    print(f"【System】キャッシュファイルから {len(stock_data_cache)} 銘柄分を読み込みました。")
    print(f"【System】そのうち有効期限内（1時間以内）のデータは {valid_cache_count} 銘柄です。")
    print(f"スキャン開始 ({len(codes)} 銘柄対象)...")

    stage1_list = []
    
    for code in tqdm(codes):
        try:
            df = None
            # 1時間以内のキャッシュがある場合のみ利用
            if code in stock_data_cache:
                last_df, last_time = stock_data_cache[code]
                if (now - last_time).total_seconds() < 3600:
                    df = last_df

            # キャッシュがない、または期限切れの場合はダウンロード
            if df is None:
                time.sleep(REQUEST_SLEEP)
                df = yf.Ticker(code).history(period=HISTORY_PERIOD)
                if not df.empty:
                    # 取得時刻とともにキャッシュを更新
                    stock_data_cache[code] = (df, datetime.now())

            if df is None or len(df) < (WINDOW_DAYS + 1): continue

            # --- ロジック判定 (v1.11) ---
            df_window = df.iloc[-WINDOW_DAYS:]
            low_window = df_window['Low'].min()
            current_price = df_window['Close'].iloc[-1]
            vol_avg = df_window['Volume'].mean()
            vol_today = df_window['Volume'].iloc[-1]
            vol_yesterday = df_window['Volume'].iloc[-2]

            is_range_s1 = df_window['Close'].iloc[:-3].max() <= (low_window * RANGE_FACTOR_S1)
            up_from_low = current_price >= (low_window * UP_FROM_LOW_RATE)
            high_vol_s1 = (vol_today >= vol_avg * VOL_MULT_S1_TODAY) and (vol_yesterday >= vol_avg * VOL_MULT_S1_YEST)

            # 金額制限チェック
            if is_range_s1 and up_from_low and high_vol_s1 and ((current_price * 100) <= PRICE_LIMIT_YEN):
                pure_code = code.replace('.T','')
                stage1_list.append({
                    "名称": name_map.get(pure_code, 'N/A'),
                    "コード": pure_code,
                    "終値": round(current_price, 1),
                    "上昇率": f"{round(((current_price/low_window)-1)*100, 1)}%"
                })
        except: continue

    # --- オートセーブ：AI分析直前に保存 ---
    try:
        with open(CACHE_FILE, 'wb') as f: 
            pickle.dump(stock_data_cache, f)
        print(f"\n[System] キャッシュ保存完了。最新の状態を保持しました。")
    except Exception as e:
        print(f"保存失敗: {e}")

    # AI分析
    if stage1_list:
        print(f"該当 {len(stage1_list)} 銘柄を Gemini 2.5 Flash で分析中...")
        prompt = f"プロの投資アナリストとして、以下の銘柄リストを詳細に分析してください：\n{stage1_list}"
        report = call_gemini_with_retry(prompt)
        print("\n=== AI分析レポート ===\n")
        print(report)
    else:
        print("該当銘柄なし。")

if __name__ == '__main__':
    run_scanner_final()