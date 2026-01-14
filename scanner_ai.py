# ==========================================================
# プログラム名: 株価選別・AI分析システム
# バージョン: 3.3.0 (調整案完全反映・スタンドアロン版ロジック統合)
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

# --- 調整案に基づく定数 ---
WINDOW_DAYS = 25
RANGE_FACTOR_S1 = 1.15      # 底値圏: +15%以内
RANGE_FACTOR_S2 = 1.10      # 厳格モード: +10%以内
UP_FROM_LOW_RATE = 1.10     # 初動: 25日安値から+10%以上
VOL_MULT_S1_TODAY = 2.0     # 出来高: 当日2.0倍
VOL_MULT_S1_YEST = 1.5      # 出来高: 前日1.5倍
VOL_MULT_S2 = 2.0           # 厳格モード: 2日連続2.0倍

# 環境変数・JST設定
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
    except:
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
    except Exception as e: print(f"送信エラー: {e}")

def run_scanner_final():
    jpx_csv = 'data_jpx.csv'
    if not os.path.exists(jpx_csv): raise FileNotFoundError("data_jpx.csvが見つかりません。")

    df_full = pd.read_csv(jpx_csv, encoding='cp932')
    df_prime = df_full[df_full['市場・商品区分'].str.contains('プライム')].copy()
    codes = [f"{str(c).strip()}.T" for c in df_prime['コード']]

    stage1_list = []
    stage2_list = []
    stats = {"total": 0, "bottom": 0, "up": 0, "vol": 0}

    print(f"--- スキャン開始 ({len(codes)}銘柄) ---")

    for code in tqdm(codes):
        try:
            stats["total"] += 1
            df = yf.Ticker(code).history(period='40d')
            if len(df) < WINDOW_DAYS: continue

            df_win = df.iloc[-WINDOW_DAYS:]
            low_25d = df_win['Low'].min()
            close_today = df_win['Close'].iloc[-1]
            vol_today = df_win['Volume'].iloc[-1]
            vol_yest  = df_win['Volume'].iloc[-2]
            vol_avg   = df_win['Volume'].mean()

            # --- 調整案ロジックの実装 ---
            
            # 1. 底値圏判定: 「5日前まで」の終値が安値から+15%以内か
            # iloc[:-5] は最新5日分を除外した過去分
            hist_close_max = df_win['Close'].iloc[:-5].max()
            is_bottom = hist_close_max <= (low_25d * RANGE_FACTOR_S1)

            # 2. 初動判定: 25日安値から今日の終値が+10%以上か
            is_up = close_today >= (low_25d * UP_FROM_LOW_RATE)

            # 3. 出来高判定: 今日2.0倍、昨日1.5倍
            is_vol = (vol_today >= vol_avg * VOL_MULT_S1_TODAY) and (vol_yest >= vol_avg * VOL_MULT_S1_YEST)

            if is_bottom:
                stats["bottom"] += 1
                if is_up:
                    stats["up"] += 1
                    if is_vol:
                        stats["vol"] += 1
                        pure_code = code.replace('.T', '')
                        name = df_prime.loc[df_prime['コード'] == int(pure_code), '銘柄名'].iloc[0]
                        item = {"コード": pure_code, "名称": name, "終値": round(close_today, 1), "出来高倍": round(vol_today/vol_avg, 1)}
                        
                        # 第二段階 (底値10%以内 且つ 2日連続2.0倍)
                        is_bottom_s2 = hist_close_max <= (low_25d * RANGE_FACTOR_S2)
                        is_vol_s2 = (vol_today >= vol_avg * VOL_MULT_S2) and (vol_yest >= vol_avg * VOL_MULT_S2)
                        if is_bottom_s2 and is_vol_s2:
                            stage2_list.append(item)
                        stage1_list.append(item)
        except: continue

    # --- レポート作成 ---
    now_jst = datetime.now(JST)
    subject = f"【AI分析】本日のスクリーニングレポート該当{len(stage1_list)}件"
    
    body = f"■ 実行日時(JST): {now_jst.strftime('%Y/%m/%d %H:%M')}\n"
    body += f"■ 判定統計:\n"
    body += f"  - 底値圏パス (5日前迄+15%内): {stats['bottom']}件\n"
    body += f"  - さらに初動パス (25日安値比+10%以上): {stats['up']}件\n"
    body += f"  - さらに出来高パス (当日2.0倍/昨日1.5倍): {stats['vol']}件\n\n"

    if not stage1_list:
        body += "本日の条件に合致する銘柄はありませんでした。"
    else:
        body += "▼▼ 【第一段階：注目候補】 初動確認銘柄 ▼▼\n"
        for i, m in enumerate(stage1_list, 1):
            body += f"{i}. {m['コード']} {m['名称']} (終値:{m['終値']}円 / 出来高:{m['出来高倍']}倍)\n"
        
        body += "\n▼▼ 【第二段階：厳格モード】 特選初動候補 ▼▼\n"
        body += "※注目候補の中から以下をさらに厳選\n"
        body += "・底値圏: 過去レンジが +10%以内\n"
        body += "・出来高: 2日連続で2.0倍以上 の急増を記録した最有力候補\n"
        body += "--------------------------------------------\n"
        if not stage2_list: body += "（該当なし）\n"
        else:
            for i, m in enumerate(stage2_list, 1):
                body += f"★ {m['コード']} {m['名称']} (終値:{m['終値']}円 / 出来高:{m['出来高倍']}倍)\n"
        
        body += f"\n\n【AIによる市場概況・分析】\n{call_gemini(f'以下の銘柄リストの展望を分析して：{stage1_list}')}"

    send_report_email(subject, body)

if __name__ == '__main__':
    run_scanner_final()