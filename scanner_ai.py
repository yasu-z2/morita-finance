# ==========================================================
# プログラム名: 株価選別システム (キャッシュ・差分更新・W分析版)
# バージョン: 3.1.0 (スタンドアロン版ロジック完全統合)
# 更新日: 2026-01-13
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
from datetime import datetime, timedelta
from tqdm import tqdm

# --- 環境変数 ---
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
MAIL_ADDRESS   = os.environ.get('MAIL_ADDRESS')
MAIL_PASSWORD  = os.environ.get('MAIL_PASSWORD')
TO_ADDRESS     = os.environ.get('TO_ADDRESS')

# --- 設定 ---
CACHE_FILE = 'stock_cache.pkl'
REQUEST_SLEEP = 0.1 # キャッシュ活用により少し短縮

def call_gemini(prompt):
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("models/gemini-1.5-flash")
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI分析エラー: {str(e)}"

def run_scanner_v310():
    start_time = time.time()
    jpx_csv = 'data_jpx.csv'
    df_full = pd.read_csv(jpx_csv, encoding='cp932')
    df_full['コード'] = df_full['コード'].astype(str).str.strip()
    df_target = df_full[df_full['市場・商品区分'].str.contains('プライム')].copy()
    codes = [f"{c}.T" for c in df_target['コード']]

    # キャッシュの読み込み
    all_history = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'rb') as f:
            all_history = pickle.load(f)
        print(f">>> キャッシュを読み込みました ({len(all_history)}銘柄分)")

    stage1_list = []
    print(f"--- スキャン開始 ({len(codes)}銘柄) ---")

    for code in tqdm(codes):
        try:
            # 差分更新ロジック
            if code in all_history:
                df = all_history[code]
                last_date = df.index[-1]
                # 最終データが昨日以前なら、今日分だけ取得して結合
                if last_date.date() < datetime.now().date():
                    new_data = yf.download(code, start=last_date + timedelta(days=1), progress=False)
                    if not new_data.empty:
                        df = pd.concat([df, new_data])
                        df = df.tail(60) # 直近60日分に制限
                        all_history[code] = df
            else:
                # 新規取得
                df = yf.Ticker(code).history(period='40d')
                all_history[code] = df

            if len(df) < 20: continue

            # --- スタンドアロン版と同一のロジック ---
            curr_p = df['Close'].iloc[-1]
            low_20 = df['Low'].iloc[-20:].min()
            ratio_from_low = (curr_p / low_20 - 1) * 100

            # 判定：安値から1%以上の立ち上がり
            if ratio_from_low >= 1.0:
                vol_ratio = df['Volume'].iloc[-1] / df['Volume'].iloc[-21:-1].mean()
                ma25 = df['Close'].rolling(window=25).mean().iloc[-1]
                dev25 = ((curr_p - ma25) / ma25) * 100
                history_list = df['Close'].tail(5).apply(lambda x: f"{round(x,1)}").tolist()
                
                pure_code = code.replace('.T', '')
                name = df_full[df_full['コード'] == pure_code].iloc[0]['銘柄名']
                
                stage1_list.append({
                    "コード": code, "名称": name, "終値": round(curr_p, 1),
                    "安値比": round(ratio_from_low, 2), "出来高倍率": round(vol_ratio, 1),
                    "25日乖離": round(dev25, 1), "5日推移": " -> ".join(history_list)
                })
            time.sleep(REQUEST_SLEEP)
        except: continue

    # キャッシュの保存
    with open(CACHE_FILE, 'wb') as f:
        pickle.dump(all_history, f)

    if not stage1_list:
        return

    # --- 2段階AI分析 ---
    top_picks = sorted(stage1_list, key=lambda x: x['安値比'], reverse=True)[:30]
    
    summary_text = "\n".join([f"- {s['名称']}({s['コード']}): 終値{s['終値']}, 安値比{s['安値比']}%" for s in top_picks])
    analysis_1 = call_gemini(f"証券アナリストとして、以下の反発銘柄群を全体俯瞰して分析してください。\n{summary_text}")

    detail_text = "\n".join([f"銘柄:{s['名称']}({s['コード']}), 終値:{s['終値']}, 出来高:{s['出来高倍率']}倍, 5日推移:{s['5日推移']}" for s in top_picks[:10]])
    analysis_2 = call_gemini(f"以下の銘柄からプロの視点で「買い」のトップ3を選び、目標指値、損切ラインを提示してください。\n{detail_text}")

    # メール送信
    elapsed = round((time.time() - start_time) / 60, 1)
    mail_body = f"■ 株価選別W分析レポート v3.1.0\n実行:{elapsed}分 / 抽出:{len(stage1_list)}件\n\n【全体分析】\n{analysis_1}\n\n【個別戦略】\n{analysis_2}"
    
    msg = MIMEText(mail_body)
    msg['Subject'] = f"【AI分析】厳選レポート ({datetime.now().strftime('%m/%d')})"
    msg['From'], msg['To'] = MAIL_ADDRESS, TO_ADDRESS
    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(MAIL_ADDRESS, MAIL_PASSWORD)
        server.send_message(msg)
        server.close()
    except: pass

if __name__ == '__main__':
    run_scanner_v310()