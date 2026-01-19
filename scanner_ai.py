"""
AI Stock Scanner System
Version: 3.6.6
Last Update: 2026-01-19

【改修内容】
1. v3.5.2 ベースの復元:
   - 銘柄リストを 'data_jpx.csv' から読み込む安定した仕様に戻しました。
2. オートセーブ機能の実装 (v3.6.0より継承):
   - AI分析の実行直前に、取得済み株価データをキャッシュファイルへ保存。
   - 万が一AIがエラーで止まっても、次回の再開時はダウンロードをスキップ可能。
3. AI分析リトライ機能の実装 (v3.6.0より継承):
   - 混雑エラー(503/Overloaded)時に15秒待機、最大3回まで自動再試行。
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

# --- 設定 ---
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
CACHE_FILE = "stock_cache.pkl"
JPX_CSV = 'data_jpx.csv'  # v3.5.2 仕様の銘柄リストファイル
REQUEST_SLEEP = 0.2 
HISTORY_PERIOD = "40d"

# --- ロジック定数 (v1.11) ---
WINDOW_DAYS = 25
PRICE_RATIO_NORMAL = 1.15
REBOUND_RATIO = 1.10
VOL_GROWTH_TODAY = 2.0
VOL_GROWTH_YESTERDAY = 1.5

def save_cache(data):
    """キャッシュをファイルに保存する（AI分析前のオートセーブ用）"""
    try:
        with open(CACHE_FILE, 'wb') as f:
            pickle.dump(data, f)
        print(f"\n[System] キャッシュを保存しました（現在 {len(data)} 銘柄分）")
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

def check_stock_logic_v1_11(df):
    """v1.11 判定ロジック"""
    if df is None or len(df) < (WINDOW_DAYS + 1): return False
    
    low_25 = df['Low'].rolling(window=WINDOW_DAYS).min().iloc[-1]
    current_price = df['Close'].iloc[-1]
    day_low = df['Low'].iloc[-1]
    vol_today = df['Volume'].iloc[-1]
    vol_yesterday = df['Volume'].iloc[-2]
    vol_day_before = df['Volume'].iloc[-3]

    cond_bottom = (current_price / low_25) <= PRICE_RATIO_NORMAL
    cond_rebound = (current_price / day_low) >= REBOUND_RATIO
    cond_volume = (vol_today >= vol_yesterday * VOL_GROWTH_TODAY) and \
                  (vol_yesterday >= vol_day_before * VOL_GROWTH_YESTERDAY)

    return cond_bottom and cond_rebound and cond_volume

def analyze_with_ai_retry(stock_list):
    """AI分析（リトライ機能付き）"""
    if not stock_list:
        return "本日は条件に合う銘柄はありませんでした。"

    client = genai.Client(api_key=GEMINI_API_KEY)
    
    prompt = f"""
あなたは決算書分析が得意なプロの投資アナリストです。
必要なら具体的な決算数値を検索し、以下の銘柄リストを詳細に分析してください。

【フォーマット】
1. 【背景】 事業内容と直近決算の数値傾向
2. 【分析】 急騰・出来高増のファンダメンタルズ要因
3. 【注目】 明日以降の注視ポイント

銘柄リスト：
{stock_list}
"""

    # --- ポイント：リトライループの実装 ---
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
                print(f"Geminiサーバー混雑中 ({attempt+1}/3). 15秒後に再試行...")
                time.sleep(15)
            else:
                return f"AI分析エラー: {e}"
    
    return "AI混雑のため分析をスキップしました。"

def main():
    # --- v3.5.2 仕様: CSVから銘柄リストを取得 ---
    if not os.path.exists(JPX_CSV):
        print(f"エラー: {JPX_CSV} が見つかりません。")
        return

    df_jpx = pd.read_csv(JPX_CSV)
    # v3.5.2 の列名に合わせて 'コード' または 'code' を指定してください
    col_name = 'コード' if 'コード' in df_jpx.columns else 'code'
    codes = [f"{str(c)}.T" for c in df_jpx[col_name]]
    
    stock_data_cache = load_cache()
    print(f"【System】キャッシュから {len(stock_data_cache)} 銘柄ロード完了。")
    
    stage1_found = [] 
    print(f"スキャン開始: {len(codes)} 銘柄")
    
    for code in tqdm(codes):
        try:
            df = None
            # キャッシュ有効判定 (1時間 = 3600秒)
            if code in stock_data_cache:
                last_df, last_time = stock_data_cache[code]
                if (datetime.now() - last_time).total_seconds() < 3600:
                    df = last_df

            if df is None:
                time.sleep(REQUEST_SLEEP)
                df = yf.Ticker(code).history(period=HISTORY_PERIOD)
                if df is None or df.empty:
                    continue 
                stock_data_cache[code] = (df, datetime.now())
            
            if check_stock_logic_v1_11(df):
                stage1_found.append(code)
        except:
            continue

    # --- ポイント：AI分析の直前に保存 ---
    save_cache(stock_data_cache)

    print(f"スクリーニング結果: {len(stage1_found)} 銘柄")
    
    # AI分析 (リトライ機能付き)
    print("AI分析実行中...")
    report_text = analyze_with_ai_retry(stage1_found)
    
    print("\n--- 分析レポート ---\n")
    print(report_text)
    # 必要に応じてここに送信関数を追加：send_email(report_text)

if __name__ == "__main__":
    main()