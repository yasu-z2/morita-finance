# ==========================================================
# プログラム名: 株価選別・AI分析システム
# バージョン: 3.3.2 (v1.11 アルゴリズム完全同期 + URL復活)
# ==========================================================

import os
import yfinance as yf
import pandas as pd
import time
import smtplib
import google.generativeai as genai
from email.mime.text import MIMEText
from email.utils import formatdate
from datetime import datetime, timedelta, timezone
from tqdm import tqdm

# --- 設定定数 (v1.11 アルゴリズムに厳密に準拠) ---
WINDOW_DAYS = 25              # 分析対象日数
RANGE_FACTOR_S1 = 1.15        # 第一段階：底値圏レンジ
RANGE_FACTOR_S2 = 1.10        # 第二段階：底値圏レンジ
UP_FROM_LOW_RATE = 1.10       # 初動判定：安値から+10%
VOL_MULT_S1_TODAY = 2.0       # 当日の出来高倍率（対25日平均）
VOL_MULT_S1_YEST = 1.5        # 前日の出来高倍率
VOL_MULT_S2 = 2.0             # 第二段階：2日連続2.0倍

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

    df_full = pd.read_csv(jpx_csv, encoding='cp932')
    df_full['コード'] = df_full['コード'].astype(str).str.strip()
    df_prime = df_full[df_full['市場・商品区分'].str.contains('プライム')].copy()
    
    name_map = dict(zip(df_prime['コード'], df_prime['銘柄名']))
    codes = [f"{c}.T" for c in name_map.keys()]

    stage1_list = []
    stage2_list = []
    stats = {"total": 0, "bottom": 0, "up": 0, "vol": 0}

    print(f"--- スキャン開始 ({len(codes)}銘柄) ---")

    for code in tqdm(codes):
        try:
            stats["total"] += 1
            # v1.11と同じ40日分取得
            df = yf.Ticker(code).history(period='40d')
            if len(df) < WINDOW_DAYS + 1: continue

            # スタンドアロン版 v1.11 のスライス基準に合わせる
            # 当日を含む直近 WINDOW_DAYS 分
            df_win = df.iloc[-WINDOW_DAYS:]
            
            # 1. 底値圏判定（当日を除く過去の終値の最大値が、25日安値の+15%以内か）
            low_25d = df_win['Low'].min()
            hist_close_max = df_win['Close'].iloc[:-1].max() # 当日を除外して判定
            is_bottom = hist_close_max <= (low_25d * RANGE_FACTOR_S1)

            # 2. 初動判定（25日安値から今日の終値が+10%以上か）
            close_today = df_win['Close'].iloc[-1]
            is_up = close_today >= (low_25d * UP_FROM_LOW_RATE)

            # 3. 出来高判定（平均は当日を含まない過去25日間）
            vol_avg = df['Volume'].iloc[-(WINDOW_DAYS+1):-1].mean()
            vol_today = df_win['Volume'].iloc[-1]
            vol_yest  = df_win['Volume'].iloc[-2]
            
            is_vol = (vol_today >= vol_avg * VOL_MULT_S1_TODAY) and (vol_yest >= vol_avg * VOL_MULT_S1_YEST)

            if is_bottom:
                stats["bottom"] += 1
                if is_up:
                    stats["up"] += 1
                    if is_vol:
                        stats["vol"] += 1
                        pure_code = code.replace('.T', '')
                        name = name_map.get(pure_code, "不明")
                        
                        item = {
                            "コード": pure_code, 
                            "名称": name, 
                            "終値": round(close_today, 1), 
                            "出来高倍": round(vol_today/vol_avg, 1),
                            "URL_Y": f"https://finance.yahoo.co.jp/quote/{pure_code}.T",
                            "URL_K": f"https://kabutan.jp/stock/chart?code={pure_code}"
                        }
                        
                        # 第二段階判定 (レンジ10% & 2日連続2.0倍)
                        is_bottom_s2 = hist_close_max <= (low_25d * RANGE_FACTOR_S2)
                        is_vol_s2 = (vol_today >= vol_avg * VOL_MULT_S2) and (vol_yest >= vol_avg * VOL_MULT_S2)
                        if is_bottom_s2 and is_vol_s2:
                            stage2_list.append(item)
                        stage1_list.append(item)
        except:
            continue

    # --- レポート作成 ---
    now_jst = datetime.now(JST)
    subject = f"【AI分析】本日のスクリーニングレポート該当{len(stage1_list)}件"
    
    body = f"■ 実行日時(JST): {now_jst.strftime('%Y/%m/%d %H:%M')}\n"
    body += f"■ 判定統計:\n"
    body += f"  - 底値圏パス (過去25日終値レンジ内): {stats['bottom']}件\n"
    body += f"  - さらに初動パス (25日安値比+10%以上): {stats['up']}件\n"
    body += f"  - さらに出来高パス (当日2.0倍/昨日1.5倍): {stats['vol']}件\n\n"

    if not stage1_list:
        body += "本日の条件に合致する銘柄はありませんでした。"
    else:
        body += "▼▼ 【第一段階：注目候補】 初動確認銘柄 ▼▼\n"
        for i, m in enumerate(stage1_list, 1):
            body += f"{i}. {m['コード']} {m['名称']} (終値:{m['終値']}円 / 出来高:{m['出来高倍']}倍)\n"
            body += f"   Yahoo: {m['URL_Y']}\n"
            body += f"   株探 : {m['URL_K']}\n"
        
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
                body += f"   Yahoo: {m['URL_Y']}\n"
                body += f"   株探 : {m['URL_K']}\n"
        
        # AI分析
        prompt = f"以下の銘柄リストは底値圏からの初動候補です。各銘柄のチャート背景を考慮し、今後の展望を簡潔に分析して：\n{stage1_list}"
        body += f"\n\n【AIによる市場概況・分析】\n{call_gemini(prompt)}"

    send_report_email(subject, body)

if __name__ == '__main__':
    run_scanner_final()