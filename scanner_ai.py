"""
AI Stock Scanner System
Version: 3.6.0
Last Update: 2026-01-19

【改修履歴】
v3.5.2: 判定ロジック v1.11 実装（底値圏・初動リバウンド・出来高爆発）
v3.6.0: 堅牢性の向上
  1. オートセーブ機能の実装: 
     AI分析実行前にキャッシュを保存し、エラー中断時のデータ消失を防止。
  2. AI分析リトライ機能の実装: 
     503 Overloadedエラー時に15秒待機して最大3回まで自動再試行。
  3. キャッシュ判定の修正: 
     .total_seconds() を使用し、日付をまたいでも正しく秒数判定するよう改善。
"""

import os
import time
import pandas as pd
import yfinance as yf
from datetime import datetime
import pickle
from tqdm import tqdm
from google import genai
from dotenv import load_dotenv
import smtplib
from email.mime.text import MIMEText
from email.utils import formatdate

# --- 設定 ---
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MAIL_ADDRESS = os.getenv("MAIL_ADDRESS")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
CACHE_FILE = "stock_cache.pkl"
REQUEST_SLEEP = 0.2 
HISTORY_PERIOD = "40d"

# --- ロジック定数 (v1.11) ---
WINDOW_DAYS = 25
PRICE_RATIO_STRICT = 1.10
PRICE_RATIO_NORMAL = 1.15
REBOUND_RATIO = 1.10
VOL_GROWTH_TODAY = 2.0
VOL_GROWTH_YESTERDAY = 1.5

def save_cache(data):
    """キャッシュをファイルに保存する"""
    try:
        with open(CACHE_FILE, 'wb') as f:
            pickle.dump(data, f)
        print(f"\n[System] キャッシュを保存しました: {CACHE_FILE}")
    except Exception as e:
        print(f"キャッシュ保存エラー: {e}")

def load_cache():
    """キャッシュを読み込む"""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'rb') as f:
                return pickle.load(f)
        except:
            return {}
    return {}

def check_stock_logic_v1_11(df, strict=False):
    """判定ロジック核心部"""
    if len(df) < (WINDOW_DAYS + 1): return False
    
    # テキスト版計算式に基づく抽出
    low_25 = df['Low'].rolling(window=WINDOW_DAYS).min().iloc[-1]
    current_price = df['Close'].iloc[-1]
    day_low = df['Low'].iloc[-1]
    vol_today = df['Volume'].iloc[-1]
    vol_yesterday = df['Volume'].iloc[-2]
    vol_day_before = df['Volume'].iloc[-3]

    # 1. 底値圏判定
    ratio_limit = PRICE_RATIO_STRICT if strict else PRICE_RATIO_NORMAL
    cond_bottom = (current_price / low_25) <= ratio_limit
    
    # 2. リバウンド判定
    cond_rebound = (current_price / day_low) >= REBOUND_RATIO
    
    # 3. 出来高判定
    cond_volume = (vol_today >= vol_yesterday * VOL_GROWTH_TODAY) and \
                  (vol_yesterday >= vol_day_before * VOL_GROWTH_YESTERDAY)

    return cond_bottom and cond_rebound and cond_volume

def analyze_with_ai_retry(stock_list):
    """AI分析を実行（503エラー時のリトライ機能付き）"""
    if not stock_list:
        return "本日はスクリーニング条件に合致する銘柄はありませんでした。"

    # APIクライアントの初期化（Gemini 2.0 Flash固定）
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    prompt = f"""
以下の銘柄リストはテクニカル条件をクリアした「底値圏からの初動候補」です。
各銘柄について、事実に基づいた簡潔な分析を行ってください。

【フォーマット】
1. 【背景】 事業内容と現在の市場環境
2. 【分析】 今回の株価・出来高急増から推測される買いの強さ
3. 【注目】 明日以降の注目ポイント

銘柄リスト：
{stock_list}
"""

    # --- リトライループ (最大3回) ---
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt
            )
            return response.text
        except Exception as e:
            error_msg = str(e).lower()
            if "503" in error_msg or "overloaded" in error_msg:
                print(f"AIサーバー混雑中 (試行 {attempt+1}/3). 15秒待機して再試行します...")
                time.sleep(15)
            else:
                return f"AI分析中にエラーが発生しました: {e}"
    
    return "AIサーバーの混雑が解消されなかったため、分析をスキップしました。"

def main():
    # 銘柄リストの読み込み（ここは既存のリスト取得処理を想定）
    codes = [f"{i}.T" for i in range(1301, 9999)] # 実際にはお使いのリストを使用
    
    stock_data_cache = load_cache()
    stage1_found = [] # 実戦
    stage2_found = [] # 厳格

    print(f"スキャン開始: {len(codes)} 銘柄")
    
    for code in tqdm(codes):
        try:
            df = None
            # キャッシュ有効判定（total_secondsを使用）
            if code in stock_data_cache:
                last_df, last_time = stock_data_cache[code]
                if (datetime.now() - last_time).total_seconds() < 3600:
                    df = last_df

            if df is None:
                time.sleep(REQUEST_SLEEP)
                df = yf.Ticker(code).history(period=HISTORY_PERIOD)
                if not df.empty:
                    stock_data_cache[code] = (df, datetime.now())
            
            if df is not None and not df.empty:
                if check_stock_logic_v1_11(df, strict=False):
                    stage1_found.append(code)
                if check_stock_logic_v1_11(df, strict=True):
                    stage2_found.append(code)
        except:
            continue

    # 【重要】AI分析の前に一度キャッシュを書き出す（オートセーブ）
    save_cache(stock_data_cache)

    print(f"抽出結果: {len(stage1_found)} 銘柄")
    
    # リトライ機能付きAI分析
    print("AI分析を実行中...")
    report_text = analyze_with_ai_retry(stage1_found)

    # メール送信処理（既存の関数を呼び出し）
    # send_email(report_text)
    print("全工程が完了しました。")

if __name__ == "__main__":
    main()