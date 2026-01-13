# ==========================================================
# プログラム名: 株価選別システム (AIアナリスト配信版)
# バージョン: 2.0.9 (銘柄名照合ロジック修正)
# 更新日: 2026-01-13
# ==========================================================

import os
import yfinance as yf
import pandas as pd
import time
import smtplib
import google.generativeai as genai
from email.mime.text import MIMEText
from email.utils import formatdate
from datetime import datetime
from tqdm import tqdm

# --- 環境変数 ---
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
MAIL_ADDRESS   = os.environ.get('MAIL_ADDRESS')
MAIL_PASSWORD  = os.environ.get('MAIL_PASSWORD')
TO_ADDRESS     = os.environ.get('TO_ADDRESS')

# --- 設定 ---
IS_DEBUG_MODE = True
DEBUG_CODES   = ["3649.T", "5471.T", "6143.T", "9869.T", "8016.T"]
REQUEST_SLEEP = 0.5

def get_ai_analysis(stage1_list):
    if not stage1_list:
        return "抽出銘柄はありませんでした。"

    try:
        genai.configure(api_key=GEMINI_API_KEY)
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        target_model = next((m for m in available_models if "1.5-flash" in m), available_models[0])
        model = genai.GenerativeModel(target_model)
        
        stocks_info = ""
        for s in stage1_list:
            stocks_info += f"""
### {s['名称']} ({s['コード']})
- 現在値: {s['終値']}円 (前日比: {s['騰落率']:.1f}%)
- 出来高: 通常の {s['出来高倍率']:.1f}倍 に急増
- 25日移動平均乖離率: {s['25日乖離']:.1f}%
- 直近5日間の終値推移: {s['5日推移']}
"""

        prompt = f"""
あなたは凄腕の証券アナリストです。
テクニカルスキャナーが抽出した以下の銘柄リスト（底値圏からの初動候補）を分析し、
投資家向けに具体的な投資戦略を日本語で作成してください。

{stocks_info}

## レポート構成
1. 本日のマーケットにおける抽出銘柄の評価
2. 個別銘柄の分析と期待値
3. 明日の具体的な立ち回りアドバイス
"""
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"【AI分析エラー】: {str(e)}"

def send_report_email(subject, body):
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = MAIL_ADDRESS
    msg['To'] = TO_ADDRESS
    msg['Date'] = formatdate(localtime=True)
    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(MAIL_ADDRESS, MAIL_PASSWORD)
        server.send_message(msg)
        server.close()
        print(">>> メール送信成功")
    except Exception as e:
        print(f">>> メール送信失敗: {e}")

def run_scanner_ai():
    now_str = datetime.now().strftime('%Y/%m/%d')
    jpx_csv = 'data_jpx.csv'
    
    # CSVの読み込みと前処理（銘柄名引き当て用）
    try:
        df_full = pd.read_csv(jpx_csv, encoding='cp932')
        # コード列を比較しやすいように文字列型に変換
        df_full['コード'] = df_full['コード'].astype(str).str.strip()
    except Exception as e:
        print(f"CSV読み込みエラー: {e}")
        return

    codes = DEBUG_CODES if IS_DEBUG_MODE else [f"{str(c).strip()}.T" for c in df_full['コード']]
    stage1_list = []

    print(f"--- {now_str} スキャン開始 (v2.0.9) ---")
    for code in tqdm(codes):
        try:
            stock = yf.Ticker(code)
            df = stock.history(period='60d')
            if len(df) < 26: continue
            
            curr_p = df['Close'].iloc[-1]
            prev_p = df['Close'].iloc[-2]
            change_rate = ((curr_p - prev_p) / prev_p) * 100
            
            vol_today = df['Volume'].iloc[-1]
            vol_avg = df['Volume'].iloc[-26:-1].mean()
            vol_ratio = vol_today / vol_avg if vol_avg != 0 else 0
            
            ma25 = df['Close'].rolling(window=25).mean().iloc[-1]
            deviation = ((curr_p - ma25) / ma25) * 100
            
            last_5_days = df['Close'].iloc[-5:].apply(lambda x: f"{round(x, 1)}円").tolist()
            history_str = " -> ".join(last_5_days)
            
            # 判定（検証モードなら無条件）
            if IS_DEBUG_MODE or (vol_ratio >= 2.0 and change_rate >= 2.0):
                # 【修正】CSVから名称を確実に取得するための検索処理
                pure_code = code.replace('.T', '')
                name_hit = df_full[df_full['コード'] == pure_code]
                
                if not name_hit.empty:
                    name = name_hit.iloc[0]['銘柄名']
                else:
                    # 見つからなかった場合のバックアップ案（yfinanceから取得試行）
                    name = stock.info.get('longName', f"銘柄コード:{pure_code}")

                stage1_list.append({
                    "コード": code, "名称": name, "終値": round(curr_p, 1),
                    "騰落率": change_rate, "出来高倍率": vol_ratio,
                    "25日乖離": deviation, "5日推移": history_str
                })
            
            time.sleep(REQUEST_SLEEP)
        except: continue

    print(f"抽出数: {len(stage1_list)}件。AI分析をリクエスト中...")
    ai_report = get_ai_analysis(stage1_list)
    
    mail_body = f"■ 自動株価選別：AI分析レポート (v2.0.9)\n"
    mail_body += "="*60 + f"\n\n{ai_report}\n\n" + "="*60
    send_report_email(f"【検証2.0.9】名称修正版 {now_str}", mail_body)

if __name__ == '__main__':
    run_scanner_ai()