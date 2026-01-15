# ==========================================================
# Version: 1.12 (Standalone with Cache)
# Date: 2026-01-15
# Comment:
#   1. キャッシュ機能統合: stock_cache.pkl を使用し実行速度を大幅向上。
#   2. CSV/TXT出力維持: 検証用データと人間用レポートを自動生成。
#   3. v1.11 ロジック固定: 判定アルゴリズムは変更なし。
# ==========================================================

import os
import logging
import yfinance as yf
import pandas as pd
import time
import pickle
from tqdm import tqdm
from datetime import datetime

# --- 設定定数 ---
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
CACHE_FILE = 'stock_cache.pkl' # AI版と共通

# ログ設定
logging.basicConfig(
    filename='scanner_error.log', 
    level=logging.ERROR, 
    format='%(asctime)s %(levelname)s: %(message)s'
)

def generate_final_report(jpx_csv):
    now = datetime.now()
    date_display = now.strftime('%Y/%m/%d')
    date_file = now.strftime('%Y%m%d')
    
    print(f"--- {date_display} 分の市場分析を開始 (キャッシュ機能有効) ---")
    
    if not os.path.exists(jpx_csv):
        print(f"エラー: {jpx_csv} が見つかりません。")
        return

    # CSV読み込み
    try:
        df_full = pd.read_csv(jpx_csv, encoding='cp932')
        condition = df_full['市場・商品区分'].str.contains('プライム') & df_full['市場・商品区分'].str.contains('内国株式')
        df_prime = df_full[condition].copy()
        codes = [f"{str(c).strip()}.T" for c in df_prime['コード']]
    except Exception as e:
        print(f"CSV読み込みエラー: {e}")
        return

    # キャッシュの読み込み
    stock_data_cache = {}
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'rb') as f:
                stock_data_cache = pickle.load(f)
            print(f"キャッシュをロードしました: {len(stock_data_cache)} 銘柄")
        except:
            print("キャッシュのロードに失敗しました。新規取得します。")

    stage1_list = []
    stage2_list = []
    all_results_for_csv = []

    for code in tqdm(codes, desc="銘柄スキャン中"):
        try:
            df = None
            # キャッシュ有効判定 (1時間以内)
            if code in stock_data_cache:
                last_df, last_time = stock_data_cache[code]
                if (datetime.now() - last_time).total_seconds() < 3600:
                    df = last_df

            # キャッシュがない、または古い場合は yfinance から取得
            if df is None:
                time.sleep(REQUEST_SLEEP)
                df = yf.Ticker(code).history(period=HISTORY_PERIOD)
                if not df.empty:
                    stock_data_cache[code] = (df, datetime.now())

            if len(df) < (WINDOW_DAYS + 1):
                continue

            # --- v1.11 判定ロジック ---
            df_window = df.iloc[-WINDOW_DAYS:]
            low_window = df_window['Low'].min()
            current_price = df_window['Close'].iloc[-1]
            vol_avg = df_window['Volume'].mean()
            vol_today = df_window['Volume'].iloc[-1]
            vol_yesterday = df_window['Volume'].iloc[-2]

            is_range_s1 = df_window['Close'].iloc[:-3].max() <= (low_window * RANGE_FACTOR_S1)
            up_from_low = current_price >= (low_window * UP_FROM_LOW_RATE)
            high_vol_s1 = (vol_today >= vol_avg * VOL_MULT_S1_TODAY) and (vol_yesterday >= vol_avg * VOL_MULT_S1_YEST)

            if is_range_s1 and up_from_low and high_vol_s1 and ((current_price * 100) <= PRICE_LIMIT_YEN):
                target1 = max(current_price * 0.97, df_window['Open'].iloc[-1])
                target2 = (low_window + current_price) / 2
                stop_loss = df['Close'].iloc[-5:].mean()
                
                code_plain = code.replace('.T','')
                name_series = df_prime.loc[df_prime['コード'].astype(str) == code_plain, '銘柄名']
                name = name_series.iloc[0] if not name_series.empty else 'N/A'

                item = {
                    "コード": code, "名称": name, "終値": round(current_price, 1),
                    "上昇率": f"{round(((current_price/low_window)-1)*100, 1)}%",
                    "第1指値": round(target1, 1), "第2指値": round(target2, 1),
                    "損切目安": round(stop_loss, 1),
                    "判定レベル": "第一段階",
                    "Yahoo": f"https://finance.yahoo.co.jp/quote/{code}"
                }

                is_range_s2 = df_window['Close'].iloc[:-1].max() <= (low_window * RANGE_FACTOR_S2)
                high_vol_s2 = (vol_today >= vol_avg * VOL_MULT_S2) and (vol_yesterday >= vol_avg * VOL_MULT_S2)
                
                if is_range_s2 and high_vol_s2:
                    item["判定レベル"] = "第二段階"
                    stage2_list.append(item)
                
                stage1_list.append(item)
                all_results_for_csv.append(item)
            
        except Exception as e:
            logging.error(f"Error processing {code}: {e}")
            continue

    # キャッシュの保存
    with open(CACHE_FILE, 'wb') as f:
        pickle.dump(stock_data_cache, f)

    # --- CSVレポート出力 ---
    if all_results_for_csv:
        csv_fn = f"Report_{date_file}.csv"
        pd.DataFrame(all_results_for_csv).to_csv(csv_fn, index=False, encoding='utf-8-sig')

    # --- テキストレポート作成 (メール本文と同じ順序を厳守) ---
    txt_fn = f"Report_{date_file}.txt"
    with open(txt_fn, 'w', encoding='utf-8') as f:
        f.write(f"■ 実行日時(JST): {now.strftime('%Y/%m/%d %H:%M')}\n\n")

        f.write("▼▼ 【第一段階：実戦モード】 注目候補 ▼▼\n")
        f.write("・底値圏: 過去25日安値から +15%以内\n")
        f.write("・初動: 当日終値が安値から +10%以上 上昇\n")
        f.write("・出来高: 当日2.0倍、前日1.5倍以上の急増\n")
        f.write("-" * 50 + "\n")
        if stage1_list:
            for res in stage1_list:
                f.write(f"■ {res['名称']} ({res['コード']})\n")
                f.write(f"   終値: {res['終値']}円 (安値比 {res['上昇率']})\n")
                f.write(f"   指値: [浅め] {res['第1指値']}円 / [本命] {res['第2指値']}円\n")
                f.write(f"   損切: {res['損切目安']}円以下\n")
                f.write(f"   Yahoo: {res['Yahoo']}\n")
                f.write("-" * 40 + "\n")
        else:
            f.write("該当なし\n\n")

        f.write("\n▼▼ 【第二段階：厳格モード】 特選初動候補 ▼▼\n")
        f.write("※注目候補の中からさらに厳選\n")
        f.write("・底値圏: 安値から +10%以内\n")
        f.write("・出来高: 2日連続で2.0倍以上 の急増を記録した最有力候補\n")
        f.write("-" * 50 + "\n")
        if stage2_list:
            for res in stage2_list:
                f.write(f"★特選銘柄: {res['名称']} ({res['コード']})\n")
                f.write(f"  価格: {res['終値']}円 / 指値1: {res['第1指値']}円 / 指値2: {res['第2指値']}円\n")
                f.write(f"  Yahoo: {res['Yahoo']}\n\n")
        else:
            f.write("該当なし\n\n")

    print(f"\n✅ 分析完了!\n・詳細CSV: Report_{date_file}.csv\n・方針TXT: {txt_fn}")

if __name__ == '__main__':
    generate_final_report('data_jpx.csv')