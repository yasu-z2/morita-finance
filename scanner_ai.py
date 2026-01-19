"""
AI Stock Scanner System
Version: 3.6.4
Last Update: 2026-01-19

【改修履歴】
v3.6.0: 堅牢性向上（オートセーブ、AIリトライ、キャッシュ判定修正）
v3.6.1: プロフェッショナル・アナリストプロンプトの実装
v3.6.4: 実行最適化
  - 銘柄リストを1,604銘柄の正常動作範囲(1301-2000番台)へ適正化。
  - 404エラー銘柄のキャッシュ汚染防止。
  - GitHub Actionsのキャッシュ復元を最大限活かす構造へ調整。
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
    """キャッシュをファイルに保存する（AI分析前のオートセーブ用）"""
    try:
        with open(CACHE_FILE, 'wb') as f:
            pickle.dump(data, f)
        print(f"\n[System] キャッシュを保存しました（現在 {len(data)} 銘柄）")
    except Exception as e:
        print(f"キャッシュ保存エラー: {e}")

def load_cache():
    """キャッシュを読み込む"""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'rb') as f:
                data = pickle.load(f)
                return data
        except:
            return {}
    return {}

def check_stock_logic_v1_11(df, strict=False):
    """判定ロジック核心部"""
    if len(df) < (WINDOW_DAYS + 1): return False
    
    low_25 = df['Low'].rolling(window=WINDOW_DAYS).min().iloc[-1]
    current_price = df['Close'].iloc[-1]
    day_low = df['Low'].iloc[-1]
    vol_today = df['Volume'].iloc[-1]
    vol_yesterday = df['Volume'].iloc[-2]
    vol_day_before = df['Volume'].iloc[-3]

    ratio_limit = PRICE_RATIO_STRICT if strict else PRICE_RATIO_NORMAL
    cond_bottom = (current_price / low_25) <= ratio_limit
    cond_rebound = (current_price / day_low) >= REBOUND_RATIO
    cond_volume = (vol_today >= vol_yesterday * VOL_GROWTH_TODAY) and \
                  (vol_yesterday >= vol_day_before * VOL_GROWTH_YESTERDAY)

    return cond_bottom and cond_rebound and cond_volume

def analyze_with_ai_retry(stock_list):
    """プロ投資アナリストによる詳細分析（リトライ機能付き）"""
    if not stock_list:
        return "本日はスクリーニング条件に合致する銘柄はありませんでした。"

    client = genai.Client(api_key=GEMINI_API_KEY)
    
    prompt = f"""
あなたは決算書分析が得意なプロの投資アナリストです。
必要なら具体的な決算数値を検索し、以下の銘柄リストを背景を考慮し詳細に分析してください。

各銘柄について、以下の【3点固定フォーマット】で出力してください。

1. 【背景】 その企業の主な事業内容と、現在の業績・市場環境（直近決算の数値傾向を含む）
2. 【分析】 テクニカル的な急騰（出来高増）の理由として考えられるファンダメンタルズ要因や材料の考察
3. 【注目】 投資家として明日以降の動きで特に注視すべきポイント（上値抵抗線や警戒すべき指標など）

銘柄リスト：
{stock_list}
"""

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt
            )
            return response.text
        except Exception as e:
            err_str = str(e).lower()
            if "503" in err_str or "overloaded" in err_str:
                print(f"Geminiサーバー混雑中 ({attempt+1}/3). 15秒後に再試行します...")
                time.sleep(15)
            else:
                return f"AI分析エラー: {e}"
    
    return "AIサーバーの混雑が解消されなかったため、分析をスキップします。"

def main():
    # --- 銘柄リスト生成の適正化 ---
    # 以前正常に動いていた「1,604銘柄」程度の範囲に設定します。
    # range(1301, 2000) で約700銘柄 + 必要に応じて追加してください。
    # 完全に復元するには [f"{i}.T" for i in 以前のリスト] とするのがベストです。
    codes = [f"{i}.T" for i in range(1301, 2500)] # ここでは範囲を絞って安定させます
    
    stock_data_cache = load_cache()
    print(f"【System】キャッシュから {len(stock_data_cache)} 銘柄をロードしました。")
    
    stage1_found = [] 

    print(f"スキャン開始: {len(codes)} 銘柄")
    
    for code in tqdm(codes):
        try:
            df = None
            # 1. キャッシュの有効チェック
            if code in stock_data_cache:
                last_df, last_time = stock_data_cache[code]
                if (datetime.now() - last_time).total_seconds() < 3600:
                    df = last_df

            # 2. キャッシュがなければダウンロード
            if df is None:
                time.sleep(REQUEST_SLEEP)