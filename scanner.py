# ==========================================================
# Version: 1.9 (Structured Text Report with Stage Titles)
# Date: 2026-01-11
# Comment: 
#   1. テキストレポートに「第一段階」と「第二段階」の表題を追加。
#   2. 該当がない場合は「該当銘柄なし」と明記。
#   3. 視認性を重視したレポートレイアウトに最適化。
# ==========================================================

import yfinance as yf
import pandas as pd
import time
from tqdm import tqdm
from datetime import datetime

def generate_final_report(jpx_csv):
    date_str = datetime.now().strftime('%Y/%m/%d')
    print(f"--- {date_str} 分の市場分析を開始 ---")
    
    try:
        df_full = pd.read_csv(jpx_csv, encoding='cp932')
        condition = df_full['市場・商品区分'].str.contains('プライム') & df_full['市場・商品区分'].str.contains('内国株式')
        df_prime = df_full[condition].copy()
        codes = [f"{str(c).strip()}.T" for c in df_prime['コード']]
    except Exception as e:
        print(f"エラー: data_jpx.csvを配置してください。 {e}")
        return

    stage1_list = []
    stage2_list = []

    for code in tqdm(codes, desc="高速スキャン中"):
        try:
            stock = yf.Ticker(code)
            df = stock.history(period='40d')
            if len(df) < 26: continue
            
            df_25 = df.iloc[-25:]
            low_25 = df_25['Low'].min()
            current_price = df_25['Close'].iloc[-1]
            vol_avg_25 = df_25['Volume'].mean()
            vol_today = df_25['Volume'].iloc[-1]
            vol_yesterday = df_25['Volume'].iloc[-2]

            # 判定ロジック
            is_range_s1 = df_25['Close'].iloc[:-3].max() <= (low_25 * 1.15)
            up_from_low = current_price >= (low_25 * 1.10)
            high_vol_s1 = (vol_today >= vol_avg_25 * 2.0) and (vol_yesterday >= vol_avg_25 * 1.5)

            if is_range_s1 and up_from_low and high_vol_s1 and ((current_price * 100) <= 200000):
                target1 = max(current_price * 0.97, df_25['Open'].iloc[-1])
                target2 = (low_25 + current_price) / 2
                stop_loss = df['Close'].iloc[-5:].mean()
                name = df_prime[df_prime['コード'].astype(str) == code.replace('.T','')]['銘柄名'].values[0]
                
                item = {
                    "コード": code, "名称": name, "終値": round(current_price, 1),
                    "上昇率": f"{round(((current_price/low_25)-1)*100, 1)}%",
                    "第1指値": round(target1, 1), "第2指値": round(target2, 1),
                    "損切目安": round(stop_loss, 1)
                }
                
                # 1段目に追加
                stage1_list.append(item)

                # 2段目の判定（より厳格な条件）
                is_range_s2 = df_25['Close'].iloc[:-1].max() <= (low_25 * 1.10)
                high_vol_s2 = (vol_today >= vol_avg_25 * 2.0) and (vol_yesterday >= vol_avg_25 * 2.0)
                if is_range_s2 and high_vol_s2:
                    stage2_list.append(item)

            time.sleep(0.01)
        except: continue

    # --- テキストレポート作成 ---
    txt_filename = f"Report_{datetime.now().strftime('%Y%m%d')}.txt"
    with open(txt_filename, 'w', encoding='utf-8') as f:
        f.write(f"【株式選別システム：本日の方針レポート】 実行日: {date_str}\n")
        f.write('='*65 + '\n\n')

        # 第2段階（厳格）の表示
        f.write("▼▼ 【第二段階：厳格モード】 究極の初動候補 ▼▼\n")
        f.write("-" * 65 + "\n")
        if stage2_list:
            for res in stage2_list:
                f.write(f"★特選銘柄: {res['名称']} ({res['コード']})\n")
                f.write(f"  価格: {res['終値']}円 / 指値1: {res['第1指値']}円 / 指値2: {res['第2指値']}円\n\n")
        else:
            f.write("該当銘柄なし（条件に合致する完璧な初動はありませんでした）\n\n")

        f.write("\n")

        # 第1段階（実戦）の表示
        f.write("▼▼ 【第一段階：実戦モード】 反発の勢いが強い候補 ▼▼\n")
        f.write("-" * 65 + "\n")
        if stage1_list:
            for res in stage1_list:
                f.write(f"■ {res['名称']} ({res['コード']})\n")
                f.write(f"   現在の価格 : {res['終値']}円 (安値から {res['上昇率']} 上昇)\n")
                f.write(f"   1. 指値シミュ  : 【第1】 {res['第1指値']}円 / 【第2】 {res['第2指値']}円\n")
                f.write(f"   2. 損切り目安  : {res['損切目安']}円 以下\n")
                f.write("-" * 45 + "\n")
        else:
            f.write("該当銘柄なし\n")

    print(f"\n✅ レポート作成完了: {txt_filename}")

if __name__ == '__main__':
    generate_final_report('data_jpx.csv')