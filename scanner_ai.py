# ==========================================================
# プログラム名: 株価選別システム (全銘柄スキャン・時間計測版)
# バージョン: 3.0.2 (STEP2: 負荷・時間検証)
# 更新日: 2026-01-13
# 概要: 
#   - 東証プライム全銘柄のスキャンを実行
#   - 実行開始から終了までの時間を計測
#   - 抽出された銘柄をリスト形式でメール送信（AI分析はスキップ）
# ==========================================================

import os
import yfinance as yf
import pandas as pd
import time
import smtplib
from email.mime.text import MIMEText
from email.utils import formatdate
from datetime import datetime
from tqdm import tqdm

# --- 環境変数 ---
MAIL_ADDRESS   = os.environ.get('MAIL_ADDRESS')
MAIL_PASSWORD  = os.environ.get('MAIL_PASSWORD')
TO_ADDRESS     = os.environ.get('TO_ADDRESS')

# --- スキャン設定 ---
IS_DEBUG_MODE = False  # STEP2では全銘柄を対象にする
REQUEST_SLEEP = 0.2    # 負荷を抑えつつ速度を出す設定

def send_report_email(subject, body):
    if not MAIL_ADDRESS: return
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

def run_step2():
    start_time = time.time()
    now_str = datetime.now().strftime('%Y/%m/%d %H:%M')
    
    # CSV読み込み
    jpx_csv = 'data_jpx.csv'
    if not os.path.exists(jpx_csv):
        send_report_email("【Error】CSV Missing", "data_jpx.csvが見つかりません。")
        return

    df_full = pd.read_csv(jpx_csv, encoding='cp932')
    df_full['コード'] = df_full['コード'].astype(str).str.strip()
    
    # プライム市場のみ抽出
    condition = df_full['市場・商品区分'].str.contains('プライム')
    df_target = df_full[condition].copy()
    codes = [f"{c}.T" for c in df_target['コード']]
    
    print(f"スキャン対象: {len(codes)} 銘柄")
    stage1_list = []

    # スキャン実行
    for code in tqdm(codes):
        try:
            stock = yf.Ticker(code)
            df = stock.history(period='35d')
            if len(df) < 26: continue
            
            curr_p = df['Close'].iloc[-1]
            prev_p = df['Close'].iloc[-2]
            change_rate = ((curr_p - prev_p) / prev_p) * 100
            
            vol_today = df['Volume'].iloc[-1]
            vol_avg = df['Volume'].iloc[-26:-1].mean()
            vol_ratio = vol_today / vol_avg if vol_avg != 0 else 0
            
            # 本番用判定ロジック (出来高2倍以上 & 2%以上上昇)
            if vol_ratio >= 2.0 and change_rate >= 2.0:
                pure_code = code.replace('.T', '')
                name = df_full[df_full['コード'] == pure_code].iloc[0]['銘柄名']
                stage1_list.append(f"- {name} ({code}): 終値{round(curr_p,1)}円 / 出来高{round(vol_ratio,1)}倍")
            
            time.sleep(REQUEST_SLEEP)
        except:
            continue

    end_time = time.time()
    elapsed_min = round((end_time - start_time) / 60, 1)
    
    # レポート作成
    mail_body = f"■ STEP2: 全銘柄スキャン完了レポート\n"
    mail_body += f"実行日: {now_str}\n"
    mail_body += f"総スキャン数: {len(codes)} 銘柄\n"
    mail_body += f"総実行時間: {elapsed_min} 分\n"
    mail_body += f"抽出数: {len(stage1_list)} 銘柄\n"
    mail_body += "------------------------------------------\n"
    mail_body += "\n".join(stage1_list) if stage1_list else "条件に合致する銘柄はありませんでした。"
    
    send_report_email(f"【STEP2】全銘柄スキャン完了 ({len(stage1_list)}件)", mail_body)

if __name__ == '__main__':
    run_step2()