"""
AI Stock Scanner System
Version: 3.6.8
Last Update: 2026-01-19

【改修内容】
1. v1.11 アルゴリズム固定定数への完全準拠:
   - 定数名と値を指定通りに修正。
   - 投資金額制限（PRICE_LIMIT_YEN = 200,000円）の条件を追加。
2. 日本語文字コード・CSV読み込みの安定化:
   - cp932/utf-8 の自動フォールバックと数値変換を実装。
3. 堅牢性の維持:
   - オートセーブ、AI分析リトライ機能を継続。
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

# --- v1.11 アルゴリズム固定定数 (完全一致) ---
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
JPX_CSV = 'data_jpx.csv'

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

def save_cache(data):
    """AI分析前に株価データを保存"""
    try:
        with open(CACHE_FILE, 'wb') as f:
            pickle.dump(data, f)
        print(f"\n[System] キャッシュを保存しました（現在 {len(data)} 銘柄分）")
    except Exception as e:
        print(f"キャッシュ保存エラー: {e}")

def load_cache():
    """キャッシュをロード"""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'rb') as f:
                return pickle.load(f)
        except:
            return {}
    return {}

def check_stock_logic_v1_11(df):
    """v1.11 指定アルゴリズムに準拠した判定"""
    if df is None or len(df) < (WINDOW_DAYS + 1): return False
    
    # 最新データの取得
    current_price = df['Close'].iloc[-1]
    day_low = df['Low'].iloc[-1]
    vol_today = df['Volume'].iloc[-1]
    vol_yesterday = df['Volume'].iloc[-2]
    vol_day_before = df['Volume'].iloc[-3]
    
    # 25日間安値
    low_25 = df['Low'].rolling(window=WINDOW_DAYS).min().iloc[-1]

    # --- 判定開始 ---
    
    # 0. 投資金額制限 (100株で20万円以下)
    if (current_price * 100) > PRICE_LIMIT_YEN:
        return False

    # 1. 底値圏判定 (RANGE_FACTOR_S1 = 1.15)
    cond_bottom = (current_price / low_25) <= RANGE_FACTOR_S1
    
    # 2. リバウンド判定 (UP_FROM_LOW_RATE = 1.10)
    cond_rebound = (current_price / day_low) >= UP_FROM_LOW_RATE
    
    # 3. 出来高判定 (TODAY >= YEST * 2.0 AND YEST >= DAY_BEFORE * 1.5)
    cond_volume = (vol_today >= vol_yesterday * VOL_MULT_S1_TODAY) and \
                  (vol_yesterday >= vol_day_before * VOL_MULT_S1_YEST)

    return cond_bottom and cond_rebound and cond_volume

def analyze_with_ai_retry(stock_list):
    """AI分析（503混雑時のリトライ機能付き）"""
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
                print(f"Gemini混雑中 ({attempt+1}/3). 15秒待機...")
                time.sleep(15)
            else:
                return f"AI分析エラー: {e}"
    
    return "AI混雑のため、詳細分析を完了できませんでした。"

def main():
    if not os.path.exists(JPX_CSV):
        print(f"エラー: {JPX_CSV} が見つかりません。")
        return

    # 文字コード対応のCSVロード
    try:
        df_jpx = pd.read_csv(JPX_CSV, encoding='cp932')
    except:
        df_jpx = pd.read_csv(JPX_CSV, encoding='utf-8')

    col_name = 'コード' if 'コード' in df_jpx.columns else 'code'
    codes = [f"{str(int(c))}.T" for c in df_jpx[col_name] if pd.notnull(c)]
    
    stock_data_cache = load_cache()
    print(f"【System】キャッシュから {len(stock_data_cache)} 銘柄ロード完了。")
    
    stage1_found = [] 
    print(f"スキャン開始: {len(codes)} 銘柄")
    
    for code in tqdm(codes):
        try:
            df = None
            # キャッシュ有効判定
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
            
            # ロジック判定 (金額制限含む)
            if check_stock_logic_v1_11(df):
                stage1_found.append(code)
        except:
            continue

    # AI分析前にオートセーブ
    save_cache(stock_data_cache)

    print(f"スクリーニング結果: {len(stage1_found)} 銘柄")
    
    print("AI分析実行中...")
    report_text = analyze_with_ai_retry(stage1_found)
    print("\n--- 分析レポート ---\n")
    print(report_text)

if __name__ == "__main__":
    main()