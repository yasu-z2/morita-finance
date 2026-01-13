# ==========================================================
# プログラム名: 株価選別システム (2段階AI分析・本番版)
# バージョン: 3.0.4 (STEP3: ロジック統一・W分析)
# 更新日: 2026-01-13
# 概要: 
#   - ロジックを「安値比（リバウンド狙い）」に完全統一
#   - 1次抽出銘柄へのAI分析 ＋ 2次厳選銘柄への詳細戦略分析
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
REQUEST_SLEEP = 0.2

def call_gemini(prompt):
    """Gemini APIを呼び出す共通関数"""
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI分析エラー: {str(e)}"

def run_step3_final():
    start_time = time.time()
    jpx_csv = 'data_jpx.csv'
    df_full = pd.read_csv(jpx_csv, encoding='cp932')
    df_full['コード'] = df_full['コード'].astype(str).str.strip()
    
    df_target = df_full[df_full['市場・商品区分'].str.contains('プライム')].copy()
    codes = [f"{c}.T" for c in df_target['コード']]
    
    stage1_list = []
    print(f"--- 1次スキャン開始 ({len(codes)}銘柄) ---")

    for code in tqdm(codes):
        try:
            stock = yf.Ticker(code)
            df = stock.history(period='35d')
            if len(df) < 20: continue
            
            curr_p = df['Close'].iloc[-1]
            low_20 = df['Low'].iloc[-20:].min()
            # 当初の目的：安値から1%以上の上昇
            ratio_from_low = (curr_p / low_20 - 1) * 100
            
            if ratio_from_low >= 1.0:
                # テクニカル指標の準備
                vol_ratio = df['Volume'].iloc[-1] / df['Volume'].iloc[-21:-1].mean()
                ma25 = df['Close'].rolling(window=25).mean().iloc[-1]
                dev25 = ((curr_p - ma25) / ma25) * 100
                history = " -> ".join(df['Close'].iloc[-5:].apply(lambda x: f"{round(x,1)}").tolist())
                
                pure_code = code.replace('.T', '')
                name = df_full[df_full['コード'] == pure_code].iloc[0]['銘柄名']
                
                stage1_list.append({
                    "コード": code, "名称": name, "終値": round(curr_p, 1),
                    "安値比": round(ratio_from_low, 2), "出来高倍率": round(vol_ratio, 1),
                    "25日乖離": round(dev25, 1), "5日推移": history
                })
            time.sleep(REQUEST_SLEEP)
        except: continue

    if not stage1_list:
        send_report_email("本日の抽出結果", "条件に合致する銘柄はありませんでした。")
        return

    # --- 第1段階：1次抽出銘柄の全体分析 ---
    stocks_summary = "\n".join([f"- {s['名称']}({s['コード']}): 終値{s['終値']}円, 安値比{s['安値比']}%" for s in stage1_list])
    prompt1 = f"""
あなたは証券アナリストです。底値圏から反発の兆候を見せた以下の銘柄群について、
現在の市場地合いを踏まえた全体的な分析レポートを作成してください。

【銘柄リスト】
{stocks_summary}
"""
    analysis_1 = call_gemini(prompt1)

    # --- 第2段階：トップ銘柄の厳選と詳細戦略 ---
    stocks_detail = ""
    for s in stage1_list:
        stocks_detail += f"銘柄:{s['名称']}({s['コード']}), 終値:{s['終値']}, 出来高倍率:{s['出来高倍率']}, 25日乖離:{s['25日乖離']}, 推移:{s['5日推移']}\n"

    prompt2 = f"""
以下の銘柄リストから、特に「明日買うべき初動銘柄」を3〜5件厳選し、
それぞれに対してプロの投資戦略（具体的な期待値、目標指値、損切りライン）を提示してください。

【詳細データ】
{stocks_detail}
"""
    analysis_2 = call_gemini(prompt2)

    # --- レポート送信 ---
    elapsed = round((time.time() - start_time) / 60, 1)
    mail_body = f"■ 株価選別システム：W分析レポート (v3.0.4)\n"
    mail_body += f"総実行時間: {elapsed}分 / 1次抽出: {len(stage1_list)}件\n\n"
    mail_body += "【第1段階：1次抽出銘柄・全体俯瞰】\n" + "-"*40 + "\n" + analysis_1 + "\n\n"
    mail_body += "【第2段階：AI厳選・個別投資戦略】\n" + "-"*40 + "\n" + analysis_2
    
    send_report_email(f"【2段階AI分析】本日の厳選銘柄レポート ({datetime.now().strftime('%m/%d')})", mail_body)

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
    except Exception as e: print(f">>> 送信失敗: {e}")

if __name__ == '__main__':
    run_step3_final()