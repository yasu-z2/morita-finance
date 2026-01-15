# ==========================================================
# Version: 1.11 (Final Stable Version)
# Date: 2026-01-12
# Comment:
#   1. CSV出力の復活: 検証用に詳細データを Report_yyyymmdd.csv に保存。
#   2. アクセス制限対策: REQUEST_SLEEP を 0.1 に調整。
#   3. 判定精度の向上: 安値からの上昇率に加え、終値ベースの推移も考慮。
# ==========================================================

import os
import logging
import yfinance as yf
import pandas as pd
import time
from tqdm import tqdm
from datetime import datetime

# --- 設定定数 (チューニング用) ---
HISTORY_PERIOD = '40d'        # データ取得期間
WINDOW_DAYS = 25              # 分析対象日数
RANGE_FACTOR_S1 = 1.15        # 第一段階：底値圏レンジ (1.15 = +15%以内)
RANGE_FACTOR_S2 = 1.10        # 第二段階：底値圏レンジ (1.10 = +10%以内)
UP_FROM_LOW_RATE = 1.10       # 初動判定：安値から何%上げたか (1.10 = +10%)
VOL_MULT_S1_TODAY = 2.0       # 当日の出来高倍率（対25日平均）
VOL_MULT_S1_YEST = 1.5        # 前日の出来高倍率
VOL_MULT_S2 = 2.0             # 第二段階：前日・当日ともに2倍以上
PRICE_LIMIT_YEN = 200000      # 投資金額上限（株価×100株）
REQUEST_SLEEP = 0.1           # サーバー負荷軽減のための待機時間

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
    
    print(f"--- {date_display} 分の市場分析を開始 ---")
    
    if not os.path.exists(jpx_csv):
        print(f"エラー: {jpx_csv} が見つかりません。")
        return

    try:
        df_full = pd.read_csv(jpx_csv, encoding='cp932')
        # 東証プライム市場の個別株に絞り込み
        condition = df_full['市場・商品区分'].str.contains('プライム') & df_full['市場・商品区分'].str.contains('内国株式')
        df_prime = df_full[condition].copy()
        codes = [f"{str(c).strip()}.T" for c in df_prime['コード']]
    except Exception as e:
        print(f"CSV読み込みエラー: {e}")
        return

    stage1_list = []
    stage2_list = []
    all_results_for_csv = []

    for code in tqdm(codes, desc="全銘柄スキャン中"):
        try:
            stock = yf.Ticker(code)
            df = stock.history(period=HISTORY_PERIOD)
            
            # 必要な日数が確保できない場合はスキップ
            if len(df) < (WINDOW_DAYS + 1):
                continue

            df_window = df.iloc[-WINDOW_DAYS:]
            low_window = df_window['Low'].min()
            current_price = df_window['Close'].iloc[-1]
            vol_avg = df_window['Volume'].mean()
            vol_today = df_window['Volume'].iloc[-1]
            vol_yesterday = df_window['Volume'].iloc[-2]

            # --- 判定ロジック ---
            # 1. 底値圏での停滞（過去25日の終値が安値から一定範囲内）
            is_range_s1 = df_window['Close'].iloc[:-3].max() <= (low_window * RANGE_FACTOR_S1)
            # 2. 初動の跳ね上がり（安値から10%以上上昇）
            up_from_low = current_price >= (low_window * UP_FROM_LOW_RATE)
            # 3. 出来高の急増
            high_vol_s1 = (vol_today >= vol_avg * VOL_MULT_S1_TODAY) and (vol_yesterday >= vol_avg * VOL_MULT_S1_YEST)

            # 総合判定
            if is_range_s1 and up_from_low and high_vol_s1 and ((current_price * 100) <= PRICE_LIMIT_YEN):
                # 指値計算
                target1 = max(current_price * 0.97, df_window['Open'].iloc[-1])
                target2 = (low_window + current_price) / 2
                stop_loss = df['Close'].iloc[-5:].mean()
                
                # 名称取得
                code_plain = code.replace('.T','')
                name_series = df_prime.loc[df_prime['コード'].astype(str) == code_plain, '銘柄名']
                name = name_series.iloc[0] if not name_series.empty else 'N/A'

                item = {
                    "コード": code, "名称": name, "終値": round(current_price, 1),
                    "上昇率": f"{round(((current_price/low_window)-1)*100, 1)}%",
                    "第1指値": round(target1, 1), "第2指値": round(target2, 1),
                    "損切目安": round(stop_loss, 1),
                    "判定レベル": "第一段階"
                }

                # 第二段階の判定（より厳格な条件）
                is_range_s2 = df_window['Close'].iloc[:-1].max() <= (low_window * RANGE_FACTOR_S2)
                high_vol_s2 = (vol_today >= vol_avg * VOL_MULT_S2) and (vol_yesterday >= vol_avg * VOL_MULT_S2)
                
                if is_range_s2 and high_vol_s2:
                    item["判定レベル"] = "第二段階"
                    stage2_list.append(item)
                
                stage1_list.append(item)
                all_results_for_csv.append(item)

            time.sleep(REQUEST_SLEEP)
            
        except Exception as e:
            logging.error(f"Error processing {code}: {e}")
            continue

    # --- 1. CSVレポート出力 (検証用) ---
    if all_results_for_csv:
        csv_fn = f"Report_{date_file}.csv"
        pd.DataFrame(all_results_for_csv).to_csv(csv_fn, index=False, encoding='utf-8-sig')

    # --- 2. テキストレポート作成 (人間用) ---
    txt_fn = f"Report_{date_file}.txt"
    with open(txt_fn, 'w', encoding='utf-8') as f:
        f.write(f"【株式選別システム：本日の方針レポート】 実行日: {date_display}\n")
        f.write('='*65 + '\n\n')

        f.write("▼▼ 【第二段階：厳格モード】 究極の初動候補 ▼▼\n")
        f.write("-" * 65 + "\n")
        if stage2_list:
            for res in stage2_list:
                f.write(f"★特選銘柄: {res['名称']} ({res['コード']})\n")
                f.write(f"  価格: {res['終値']}円 / 指値1: {res['第1指値']}円 / 指値2: {res['第2指値']}円\n\n")
        else:
            f.write("該当なし\n\n")

        f.write("\n▼▼ 【第一段階：実戦モード】 反発の勢いが強い候補 ▼▼\n")
        f.write("-" * 65 + "\n")
        if stage1_list:
            for res in stage1_list:
                f.write(f"■ {res['名称']} ({res['コード']})\n")
                f.write(f"   終値: {res['終値']}円 (安値比 {res['上昇率']})\n")
                f.write(f"   指値: [浅め] {res['第1指値']}円 / [本命] {res['第2指値']}円\n")
                f.write(f"   損切: {res['損切目安']}円以下\n")
                f.write("-" * 45 + "\n")
        else:
            f.write("該当なし\n")

    print(f"\n✅ 分析完了!\n・詳細データ: Report_{date_file}.csv\n・方針レポート: {txt_fn}")

if __name__ == '__main__':
    generate_final_report('data_jpx.csv')