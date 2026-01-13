# ==========================================================
# プログラム名: 株価選別システム (v1.11ロジック + AI W分析)
# バージョン: 3.2.0 (キャッシュ/差分更新/動的モデル選択)
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

# --- 設定定数 (v1.11 アルゴリズム準拠) ---
WINDOW_DAYS = 25
RANGE_FACTOR_S1 = 1.15
UP_FROM_LOW_RATE = 1.10
VOL_MULT_S1_TODAY = 2.0
VOL_MULT_S1_YEST = 1.5
PRICE_LIMIT_YEN = 200000
CACHE_FILE = 'stock_cache.pkl'
REQUEST_SLEEP = 0.1

# --- 環境変数 ---
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
MAIL_ADDRESS   = os.environ.get('MAIL_ADDRESS')
MAIL_PASSWORD  = os.environ.get('MAIL_PASSWORD')
TO_ADDRESS     = os.environ.get('TO_ADDRESS')

def call_gemini(prompt):
    """利用可能なモデルを自動取得してAI分析を実行"""
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        target_model = next((m for m in models if 'gemini-1.5-flash' in m), models[0])
        model = genai.GenerativeModel(target_model)
        return model.generate_content(prompt).text
    except Exception as e:
        return f"AI分析エラー: {str(e)}"

def run_scanner_final():
    start_time = time.time()
    jpx_csv = 'data_jpx.csv'
    df_full = pd.read_csv(jpx_csv, encoding='cp932')
    df_full['コード'] = df_full['コード'].astype(str).str.strip()
    df_prime = df_full[df_full['市場・商品区分'].str.contains('プライム') & df_full['市場・商品区分'].str.contains('内国株式')].copy()
    codes = [f"{c}.T" for c in df_prime['コード']]

    # キャッシュ読み込み
    all_history = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'rb') as f: all_history = pickle.load(f)

    stage1_list = []
    print(f"--- スキャン開始 ({len(codes)}銘柄) ---")

    for code in tqdm(codes):
        try:
            # 差分更新または新規取得
            if code in all_history:
                df = all_history[code]
                if df.index[-1].date() < datetime.now().date():
                    new_data = yf.download(code, start=df.index[-1] + timedelta(days=1), progress=False)
                    if not new_data.empty:
                        df = pd.concat([df, new_data]).tail(60)
                        all_history[code] = df
            else:
                df = yf.Ticker(code).history(period='40d')
                all_history[code] = df

            if len(df) < (WINDOW_DAYS + 1): continue

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
                # v1.11 指値計算
                target1 = max(current_price * 0.97, df_window['Open'].iloc[-1])
                target2 = (low_window + current_price) / 2
                stop_loss = df['Close'].iloc[-5:].mean()
                
                pure_code = code.replace('.T', '')
                name_series = df_prime.loc[df_prime['コード'].astype(str) == pure_code, '銘柄名']
                name = name_series.iloc[0] if not name_series.empty else 'N/A'

                stage1_list.append({
                    "コード": code, "名称": name, "終値": round(current_price, 1),
                    "上昇率": round(((current_price/low_window)-1)*100, 1),
                    "第1指値": round(target1, 1), "第2指値": round(target2, 1),
                    "損切目安": round(stop_loss, 1),
                    "出来高倍率": round(vol_today/vol_avg, 1)
                })
            time.sleep(REQUEST_SLEEP)
        except: continue

    # キャッシュ保存
    with open(CACHE_FILE, 'wb') as f: pickle.dump(all_history, f)

    if not stage1_list:
        return

    # --- AI分析レポート作成 ---
    top_picks = sorted(stage1_list, key=lambda x: x['出来高倍率'], reverse=True)[:15]
    summary_data = "\n".join([f"- {s['名称']}({s['コード']}): 終値{s['終値']}円, 安値比+{s['上昇率']}%" for s in top_picks])
    
    analysis_1 = call_gemini(f"プロの証券アナリストとして、以下の底値圏反発銘柄の市場背景を分析してください。\n{summary_data}")
    
    detail_data = "\n".join([f"{s['名称']}({s['コード']}): 終値{s['終値']}, 指値1:{s['第1指値']}, 指値2:{s['第2指値']}, 損切:{s['損切目安']}" for s in top_picks[:5]])
    analysis_2 = call_gemini(f"以下の厳選銘柄に対して具体的な立ち回り戦略を作成してください。\n{detail_data}")

    # メール送信
    elapsed = round((time.time() - start_time) / 60, 1)
    mail_body = f"■ 株価選別W分析レポート v3.2.0\n実行時間: {elapsed}分 / ヒット数: {len(stage1_list)}件\n\n"
    mail_body += "【第1段階：市場俯瞰】\n" + "="*40 + "\n" + analysis_1 + "\n\n"
    mail_body += "【第2段階：投資アクション】\n" + "="*40 + "\n" + analysis_2
    
    send_report_email(f"【AI分析】本日の初動銘柄レポート ({len(stage1_list)}件)", mail_body)

def send_report_email(subject, body):
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'], msg['To'] = MAIL_ADDRESS, TO_ADDRESS
    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(MAIL_ADDRESS, MAIL_PASSWORD)
        server.send_message(msg)
        server.close()
    except: pass

if __name__ == '__main__':
    run_scanner_final()