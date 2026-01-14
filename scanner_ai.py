# ==========================================================
# プログラム名: 株価選別・AI分析システム
# バージョン: 3.2.7 (Model: gemini-2.5-flash / 統計メール対応)
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
from datetime import datetime
from tqdm import tqdm

# --- スキャン条件定数 ---
WINDOW_DAYS = 25
RANGE_FACTOR_S1 = 1.15      # 第一段階: 底値15%以内
UP_FROM_LOW_RATE = 1.10     # 第一段階: 当日安値から+10%以上の初動
VOL_MULT_S1_TODAY = 2.0     # 第一段階: 当日出来高2.0倍
VOL_MULT_S1_YEST = 1.5      # 第一段階: 前日出来高1.5倍

RANGE_FACTOR_S2 = 1.10      # 第二段階: 底値10%以内
VOL_MULT_S2 = 2.0           # 第二段階: 2日連続2.0倍以上

# 環境変数
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
MAIL_ADDRESS   = os.environ.get('MAIL_ADDRESS')
MAIL_PASSWORD  = os.environ.get('MAIL_PASSWORD')
TO_ADDRESS     = os.environ.get('TO_ADDRESS')

def call_gemini(prompt):
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-2.5-flash")
        return model.generate_content(prompt).text
    except Exception as e:
        print(f"AI分析エラー: {e}")
        return "AI分析を実行できませんでした。"

def send_report_email(subject, body):
    if not TO_ADDRESS: return
    recipient_list = [addr.strip() for addr in TO_ADDRESS.split(',')]
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = MAIL_ADDRESS
    msg['To'] = ", ".join(recipient_list)
    msg['Date'] = formatdate(localtime=True)
    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(MAIL_ADDRESS, MAIL_PASSWORD)
        server.send_message(msg, to_addrs=recipient_list)
        server.close()
    except Exception as e:
        print(f"送信エラー: {e}")

def run_scanner_final():
    jpx_csv = 'data_jpx.csv'
    if not os.path.exists(jpx_csv):
        raise FileNotFoundError("data_jpx.csv が見つかりません。")

    df_full = pd.read_csv(jpx_csv, encoding='cp932')
    df_prime = df_full[df_full['市場・商品区分'].str.contains('プライム')].copy()
    codes = [f"{str(c).strip()}.T" for c in df_prime['コード']]

    stage1_list = []
    stage2_list = []
    
    # 統計用カウンタ
    stats = {"total": 0, "bottom": 0, "up": 0, "vol": 0}

    print(f"--- スキャン開始 ({len(codes)}銘柄) ---")

    for code in tqdm(codes):
        try:
            stats["total"] += 1
            # 安定のため期間を少し長めに取得
            df = yf.Ticker(code).history(period='40d')
            if len(df) < WINDOW_DAYS: continue

            close = df['Close'].iloc[-1]
            low_today = df['Low'].iloc[-1]
            vol_today = df['Volume'].iloc[-1]
            vol_yest  = df['Volume'].iloc[-2]
            avg_vol   = df['Volume'].iloc[-WINDOW_DAYS:-1].mean()
            low_25d   = df['Low'].iloc[-WINDOW_DAYS:].min()

            # --- 判定ロジック ---
            # 1. 底値圏 (+15%以内)
            is_bottom = close <= (low_25d * RANGE_FACTOR_S1)
            # 2. 初動 (当日安値から+10%以上)
            is_up     = close >= (low_today * UP_FROM_LOW_RATE)
            # 3. 出来高 (当日2.0倍 かつ 前日1.5倍)
            is_vol    = (vol_today >= avg_vol * VOL_MULT_S1_TODAY) and (vol_yest >= avg_vol * VOL_MULT_S1_YEST)

            if is_bottom:
                stats["bottom"] += 1
                if is_up:
                    stats["up"] += 1
                    if is_vol:
                        stats["vol"] += 1
                        pure_code = code.replace('.T', '')
                        name = df_prime.loc[df_prime['コード'] == int(pure_code), '銘柄名'].iloc[0]
                        item = {
                            "コード": pure_code, 
                            "名称": name, 
                            "終値": round(close, 1), 
                            "出来高倍": round(vol_today/avg_vol, 1)
                        }
                        
                        # --- 第二段階判定 ---
                        is_bottom_s2 = close <= (low_25d * RANGE_FACTOR_S2)
                        is_vol_s2 = (vol_today >= avg_vol * VOL_MULT_S2) and (vol_yest >= avg_vol * VOL_MULT_S2)
                        
                        if is_bottom_s2 and is_vol_s2:
                            stage2_list.append(item)
                        stage1_list.append(item)
        except Exception:
            continue

    # --- メール本文作成 ---
    now_str = datetime.now().strftime('%Y/%m/%d %H:%M')
    subject = f"【スキャン結果】{now_str} - 該当{len(stage1_list)}件"
    
    body = f"■ 実行日時: {now_str}\n"
    body += f"■ スキャン対象: 東証プライム {stats['total']}銘柄\n"
    body += f"■ 判定統計:\n"
    body += f"  - 底値圏パス (+15%以内): {stats['bottom']}件\n"
    body += f"  - さらに初動パス (当日安値から+10%以上): {stats['up']}件\n"
    body += f"  - さらに出来高パス (当日2.0倍/前日1.5倍): {stats['vol']}件\n\n"

    if not stage1_list:
        body += "本日の条件に合致する銘柄はありませんでした。"
    else:
        body += "▼▼ 【第一段階：注目候補】 初動確認銘柄 ▼▼\n"
        for i, m in enumerate(stage1_list, 1):
            body += f"{i}. {m['コード']} {m['名称']} (終値:{m['終値']}円 / 出来高:{m['出来高倍']}倍)\n"
        
        body += "\n▼▼ 【第二段階：厳格モード】 特選初動候補 ▼▼\n"
        body += "※注目候補の中から以下をさらに厳選\n"
        body += "・底値圏: 安値から +10%以内\n"
        body += "・出来高: 2日連続で2.0倍以上 の急増を記録した最有力候補\n"
        body += "--------------------------------------------\n"
        
        if not stage2_list:
            body += "（該当なし）\n"
        else:
            for i, m in enumerate(stage2_list, 1):
                body += f"★ {m['コード']} {m['名称']} (終値:{m['終値']}円 / 出来高:{m['出来高倍']}倍)\n"
        
        # --- AI分析 ---
        prompt = f"以下の銘柄リストは底値圏で出来高が急増した初動候補です。今後の展望を簡潔に分析して：\n{stage1_list}"
        body += f"\n\n【AIによる市場概況・分析】\n{call_gemini(prompt)}"

    send_report_email(subject, body)
    print(f"処理完了: {len(stage1_list)}件送信")

if __name__ == '__main__':
    run_scanner_final()