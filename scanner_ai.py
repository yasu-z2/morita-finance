# ==========================================================
# プログラム名: 株価選別・AI分析システム
# バージョン: 3.3.4 (v1.11 ロジック完全コピー版)
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
from datetime import datetime, timedelta, timezone
from tqdm import tqdm

# --- 設定定数 (v1.11 と完全に同一に設定) ---
WINDOW_DAYS = 25
RANGE_FACTOR_S1 = 1.15
RANGE_FACTOR_S2 = 1.10
UP_FROM_LOW_RATE = 1.10
VOL_MULT_S1_TODAY = 2.0
VOL_MULT_S1_YEST = 1.5
VOL_MULT_S2 = 2.0
PRICE_LIMIT_YEN = 200000
REQUEST_SLEEP = 0.1

# 環境変数・JST
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
MAIL_ADDRESS   = os.environ.get('MAIL_ADDRESS')
MAIL_PASSWORD  = os.environ.get('MAIL_PASSWORD')
TO_ADDRESS     = os.environ.get('TO_ADDRESS')
JST = timezone(timedelta(hours=+9), 'JST')

def call_gemini(prompt):
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-2.5-flash")
        return model.generate_content(prompt).text
    except: return "AI分析を実行できませんでした。"

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
    except Exception as e: print(f"送信エラー: {e}")

def run_scanner_final():
    jpx_csv = 'data_jpx.csv'
    df_full = pd.read_csv(jpx_csv, encoding='cp932')
    df_full['コード'] = df_full['コード'].astype(str).str.strip()
    df_prime = df_full[df_full['市場・商品区分'].str.contains('プライム')].copy()
    name_map = dict(zip(df_prime['コード'], df_prime['銘柄名']))
    codes = [f"{c}.T" for c in name_map.keys()]

    stage1_list = []
    stage2_list = []
    stats = {"total": 0, "price_ok": 0, "bottom": 0, "up": 0, "vol": 0}

    print(f"--- スキャン開始 ({len(codes)}銘柄) ---")

    for code in tqdm(codes):
        try:
            stats["total"] += 1
            time.sleep(REQUEST_SLEEP)
            df = yf.Ticker(code).history(period='40d')
            if len(df) < 30: continue

            # --- v1.11 判定ロジック完全移植 ---
            
            # 最新データ
            close_today = df['Close'].iloc[-1]
            low_today = df['Low'].iloc[-1]
            vol_today = df['Volume'].iloc[-1]
            vol_yest = df['Volume'].iloc[-2]
            
            # 予算制限
            if (close_today * 100) > PRICE_LIMIT_YEN: continue
            stats["price_ok"] += 1

            # 過去データ窓 (当日含む25日間)
            df_win = df.iloc[-WINDOW_DAYS:]
            low_25d = df_win['Low'].min()
            avg_close_25d = df_win['Close'].mean() # ★ここが「平均」なのがv1.11の特徴
            
            # 平均出来高 (当日を含まない過去25日間)
            avg_vol_25d = df['Volume'].iloc[-(WINDOW_DAYS+1):-1].mean()

            # 1. 底値圏判定
            is_bottom = avg_close_25d <= (low_25d * RANGE_FACTOR_S1)

            # 2. 初動判定
            is_up = close_today >= (low_25d * UP_FROM_LOW_RATE)

            # 3. 出来高判定
            is_vol = (vol_today >= avg_vol_25d * VOL_MULT_S1_TODAY) and (vol_yest >= avg_vol_25d * VOL_MULT_S1_YEST)

            if is_bottom:
                stats["bottom"] += 1
                if is_up:
                    stats["up"] += 1
                    if is_vol:
                        stats["vol"] += 1
                        pure_code = code.replace('.T', '')
                        name = name_map.get(pure_code, "不明")
                        
                        # 指値・損切計算 (v1.11から移植)
                        entry1 = round(close_today * 0.98, 1) # 浅め
                        entry2 = round(low_25d * 1.05, 1)    # 本命
                        exit_loss = round(low_25d * 0.98, 1) # 損切
                        
                        item = {
                            "コード": pure_code, "名称": name, "終値": round(close_today, 1),
                            "出来高倍": round(vol_today/avg_vol_25d, 1),
                            "指値1": entry1, "指値2": entry2, "損切": exit_loss,
                            "URL_Y": f"https://finance.yahoo.co.jp/quote/{pure_code}.T",
                            "URL_K": f"https://kabutan.jp/stock/chart?code={pure_code}"
                        }
                        
                        # 第二段階判定
                        is_bottom_s2 = avg_close_25d <= (low_25d * RANGE_FACTOR_S2)
                        is_vol_s2 = (vol_today >= avg_vol_25d * VOL_MULT_S2) and (vol_yest >= avg_vol_25d * VOL_MULT_S2)
                        if is_bottom_s2 and is_vol_s2:
                            stage2_list.append(item)
                        stage1_list.append(item)
        except: continue

    # --- レポート作成 ---
    now_jst = datetime.now(JST)
    subject = f"【AI分析】本日のスクリーニングレポート該当{len(stage1_list)}件"
    
    body = f"■ 実行日時(JST): {now_jst.strftime('%Y/%m/%d %H:%M')}\n"
    body += f"■ 判定統計:\n"
    body += f"  - スキャン対象: {stats['total']}銘柄\n"
    body += f"  - 予算内(20万円以下): {stats['price_ok']}件\n"
    body += f"  - 底値圏パス(25日終値平均): {stats['bottom']}件\n"
    body += f"  - さらに初動パス: {stats['up']}件\n"
    body += f"  - さらに出来高パス: {stats['vol']}件\n\n"

    if not stage1_list:
        body += "本日の条件に合致する銘柄はありませんでした。"
    else:
        body += "▼▼ 【第一段階：注目候補】 初動確認銘柄 ▼▼\n"
        for i, m in enumerate(stage1_list, 1):
            body += f"{i}. {m['コード']} {m['名称']} (終値:{m['終値']}円 / 出来高:{m['出来高倍']}倍)\n"
            body += f"   指値目安: {m['指値1']}円 / {m['指値2']}円 (損切:{m['損切']}円)\n"
            body += f"   Yahoo: {m['URL_Y']}\n   株探 : {m['URL_K']}\n"
            body += "-" * 30 + "\n"
        
        body += "\n▼▼ 【第二段階：厳格モード】 特選初動候補 ▼▼\n"
        if not stage2_list:
            body += "（該当なし）\n"
        else:
            for i, m in enumerate(stage2_list, 1):
                body += f"★ {m['コード']} {m['名称']} (終値:{m['終値']}円)\n"
                body += f"   指値目安: {m['指値1']}円 / {m['指値2']}円\n"
                body += f"   Yahoo: {m['URL_Y']}\n   株探 : {m['URL_K']}\n"
        
        body += f"\n\n【AIによる市場概況・分析】\n{call_gemini(f'以下の銘柄リストは底値圏からの初動候補です。分析して：{stage1_list}')}"

    send_report_email(subject, body)

if __name__ == '__main__':
    run_scanner_final()