# ==========================================================
# プログラム名: 株価選別・AI分析システム
# バージョン: 3.3.1 (データ照合バグ修正・ロジック完全統合)
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
RANGE_FACTOR_S1 = 1.15      # 第一段階: 底値15%以内
RANGE_FACTOR_S2 = 1.10      # 第二段階: 底値10%以内
UP_FROM_LOW_RATE = 1.10     # 初動: 25日安値から+10%以上
VOL_MULT_S1_TODAY = 2.0     # 出来高: 当日2.0倍
VOL_MULT_S1_YEST = 1.5      # 出来高: 前日1.5倍
VOL_MULT_S2 = 2.0           # 厳格モード: 2日連続2.0倍

# 環境変数
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
    except Exception as e:
        print(f"送信エラー: {e}")

def run_scanner_final():
    jpx_csv = 'data_jpx.csv'
    if not os.path.exists(jpx_csv):
        raise FileNotFoundError("data_jpx.csvが見つかりません。")

    # データ読み込み時の型を安定させる
    df_full = pd.read_csv(jpx_csv, encoding='cp932')
    df_full['コード'] = df_full['コード'].astype(str).str.strip()
    df_prime = df_full[df_full['市場・商品区分'].str.contains('プライム')].copy()
    
    # 銘柄名検索用の辞書を先に作成（高速化とエラー回避）
    name_map = dict(zip(df_prime['コード'], df_prime['銘柄名']))
    codes = [f"{c}.T" for c in name_map.keys()]

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

            # --- ロジック判定 ---
            # 1. 底値圏: 「5日前まで」の終値が安値から15%以内
            hist_close_max = df_win['Close'].iloc[:-5].max()
            is_bottom = hist_close_max <= (low_25d * RANGE_FACTOR_S1)

            # 2. 初動: 25日安値から+10%以上
            is_up = close_today >= (low_25d * UP_FROM_LOW_RATE)

            # 3. 出来高: 当日2.0倍、昨日1.5倍
            is_vol = (vol_today >= vol_avg * VOL_MULT_S1_TODAY) and (vol_yest >= vol_avg * VOL_MULT_S1_YEST)

            if is_bottom:
                stats["bottom"] += 1
                if is_up:
                    stats["up"] += 1
                    if is_vol:
                        stats["vol"] += 1
                        pure_code = code.replace('.T', '')
                        # 辞書から安全に名称取得
                        name = name_map.get(pure_code, "不明")
                        
                        item = {
                            "コード": pure_code, 
                            "名称": name, 
                            "終値": round(close_today, 1), 
                            "出来高倍": round(vol_today/vol_avg, 1)
                        }
                        
                        # 第二段階判定
                        is_bottom_s2 = hist_close_max <= (low_25d * RANGE_FACTOR_S2)
                        is_vol_s2 = (vol_today >= vol_avg * VOL_MULT_S2) and (vol_yest >= vol_avg * VOL_MULT_S2)
                        if is_bottom_s2 and is_vol_s2:
                            stage2_list.append(item)
                        stage1_list.append(item)
        except Exception as e:
            # 念のためエラー内容をコンソールに出力
            print(f"Error skipping {code}: {e}")
            continue

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
        if not stage2_list:
            body += "（該当なし）\n"
        else:
            for i, m in enumerate(stage2_list, 1):
                body += f"★ {m['コード']} {m['名称']} (終値:{m['終値']}円 / 出来高:{m['出来高倍']}倍)\n"
        
        # AI分析
        prompt = f"以下の銘柄リストは底値圏からの初動候補です。今後の展望を分析して：\n{stage1_list}"
        body += f"\n\n【AIによる市場概況・分析】\n{call_gemini(prompt)}"

    send_report_email(subject, body)

if __name__ == '__main__':
    run_scanner_final()