# ==========================================================
# プログラム名: 株価選別・AI分析システム (2026年最新安定版)
# バージョン: 3.2.3 (Gemini 2.5 Flash 完全対応)
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
RANGE_FACTOR_S1 = 1.15         # 第一段階：底値圏レンジ (15%以内)
RANGE_FACTOR_S2 = 1.10         # 第二段階：底値圏レンジ (10%以内)
UP_FROM_LOW_RATE = 1.10        # 安値からの反発率 (10%以上)
VOL_MULT_S1_TODAY = 2.0        # 第一段階：当日出来高倍率
VOL_MULT_S1_YEST = 1.5         # 第一段階：前日出来高倍率
VOL_MULT_S2 = 2.0              # 第二段階：出来高倍率 (厳格)
PRICE_LIMIT_YEN = 200000       # 投資上限額 (20万円)
CACHE_FILE = 'stock_cache.pkl'
REQUEST_SLEEP = 0.1

# --- 環境変数 (GitHub Secretsから取得) ---
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
MAIL_ADDRESS   = os.environ.get('MAIL_ADDRESS')
MAIL_PASSWORD  = os.environ.get('MAIL_PASSWORD')
TO_ADDRESS     = os.environ.get('TO_ADDRESS')

def call_gemini(prompt):
    """最新の Gemini 2.5 Flash を使用してAI分析を実行"""
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        # 推奨モデル名を明示的に指定
        model_name = "gemini-2.5-flash"
        
        # モデルの存在確認とフォールバック
        models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        if not any(model_name in m for m in models):
            # 万が一2.5が見つからない場合はリストの先頭を使用
            model_name = models[0]
            
        model = genai.GenerativeModel(model_name)
        return model.generate_content(prompt).text
    except Exception as e:
        return f"AI分析エラー: {str(e)}"

def send_report_email(subject, body):
    """複数宛先への一斉送信に対応"""
    if not TO_ADDRESS:
        print("送信先(TO_ADDRESS)が設定されていません。")
        return

    # カンマ区切りの文字列をリストに変換
    recipient_list = [addr.strip() for addr in TO_ADDRESS.split(',')]

    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = MAIL_ADDRESS
    msg['To'] = ", ".join(recipient_list) # メールの宛先欄に全員分表示
    msg['Date'] = formatdate(localtime=True)

    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(MAIL_ADDRESS, MAIL_PASSWORD)
        # 実際の送信（to_addrsにリストを渡す）
        server.send_message(msg, to_addrs=recipient_list)
        server.close()
        print(f">>> {len(recipient_list)} 件の宛先へ送信しました。")
    except Exception as e:
        print(f">>> 送信エラー: {e}")

def run_scanner_final():
    start_time = time.time()
    jpx_csv = 'data_jpx.csv'
    
    if not os.path.exists(jpx_csv):
        print("エラー: data_jpx.csv が見つかりません。")
        return

    # 東証プライム銘柄の読み込み
    df_full = pd.read_csv(jpx_csv, encoding='cp932')
    df_full['コード'] = df_full['コード'].astype(str).str.strip()
    df_prime = df_full[df_full['市場・商品区分'].str.contains('プライム') & df_full['市場・商品区分'].str.contains('内国株式')].copy()
    codes = [f"{c}.T" for c in df_prime['コード']]

    # キャッシュ読み込み
    all_history = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'rb') as f:
            all_history = pickle.load(f)

    stage1_list = []
    stage2_list = []
    print(f"--- スキャン開始 ({len(codes)}銘柄) ---")

    for code in tqdm(codes):
        try:
            # データ取得（キャッシュ活用）
            if code in all_history:
                df = all_history[code]
                # 最新データが必要かチェック
                if df.index[-1].date() < datetime.now().date():
                    new_data = yf.download(code, start=df.index[-1] + timedelta(days=1), progress=False)
                    if not new_data.empty:
                        df = pd.concat([df, new_data]).tail(60)
                        all_history[code] = df
            else:
                df = yf.Ticker(code).history(period='40d')
                all_history[code] = df

            if len(df) < (WINDOW_DAYS + 1): continue

            # ロジック判定
            df_window = df.iloc[-WINDOW_DAYS:]
            low_window = df_window['Low'].min()
            current_price = df_window['Close'].iloc[-1]
            vol_avg = df_window['Volume'].mean()
            vol_today = df_window['Volume'].iloc[-1]
            vol_yesterday = df_window['Volume'].iloc[-2]

            # 第一段階条件
            is_range_s1 = df_window['Close'].iloc[:-3].max() <= (low_window * RANGE_FACTOR_S1)
            up_from_low = current_price >= (low_window * UP_FROM_LOW_RATE)
            high_vol_s1 = (vol_today >= vol_avg * VOL_MULT_S1_TODAY) and (vol_yesterday >= vol_avg * VOL_MULT_S1_YEST)

            if is_range_s1 and up_from_low and high_vol_s1 and ((current_price * 100) <= PRICE_LIMIT_YEN):
                # 共通データの構築
                target1 = max(current_price * 0.97, df_window['Open'].iloc[-1])
                target2 = (low_window + current_price) / 2
                stop_loss = df['Close'].iloc[-5:].mean()
                pure_code = code.replace('.T', '')
                name = df_prime.loc[df_prime['コード'].astype(str) == pure_code, '銘柄名'].iloc[0]

                item = {
                    "コード": code, "名称": name, "終値": round(float(current_price), 1),
                    "上昇率": round(((float(current_price)/low_window)-1)*100, 1),
                    "第1指値": round(float(target1), 1), "第2指値": round(float(target2), 1),
                    "損切目安": round(float(stop_loss), 1), "出来高倍率": round(float(vol_today/vol_avg), 1)
                }

                # 第二段階判定 (厳格条件)
                is_range_s2 = df_window['Close'].iloc[:-1].max() <= (low_window * RANGE_FACTOR_S2)
                high_vol_s2 = (vol_today >= vol_avg * VOL_MULT_S2) and (vol_yesterday >= vol_avg * VOL_MULT_S2)
                
                if is_range_s2 and high_vol_s2:
                    stage2_list.append(item)
                
                stage1_list.append(item)

            time.sleep(REQUEST_SLEEP)
        except Exception:
            continue

    # キャッシュ保存
    with open(CACHE_FILE, 'wb') as f:
        pickle.dump(all_history, f)

    if not stage1_list:
        print("本日の該当銘柄はありませんでした。")
        return

    # --- AI分析の実行 ---
    top_picks = sorted(stage1_list, key=lambda x: x['出来高倍率'], reverse=True)[:15]
    summary_data = "\n".join([f"- {s['名称']}({s['コード']}): 終値{s['終値']}円" for s in top_picks])
    analysis_1 = call_gemini(f"プロの証券アナリストとして、以下の銘柄の反発要因を市場背景と併せて詳細に分析してください。\n{summary_data}")
    
    detail_data = "\n".join([f"{s['名称']}({s['コード']}): 終値{s['終値']}, 指値1:{s['第1指値']}, 損切:{s['損切目安']}" for s in top_picks[:5]])
    analysis_2 = call_gemini(f"以下の厳選銘柄に対して、明日以降の具体的なトレード戦略（期待値とリスク管理）を提示してください。\n{detail_data}")

    # --- メール本文の作成 ---
    elapsed = round((time.time() - start_time) / 60, 1)
    mail_body = f"■ 株価選別W分析レポート v3.2.3 (Gemini 2.5 Flash)\n実行時間: {elapsed}分 / 抽出数: {len(stage1_list)}件\n\n"
    
    mail_body += "▼▼ 【第二段階：厳格モード】 特選初動候補 ▼▼\n"
    mail_body += "-" * 50 + "\n"
    if stage2_list:
        for s in stage2_list:
            mail_body += f"★特選: {s['名称']} ({s['コード']})\n"
            mail_body += f"   価格: {s['終値']}円 / [本命指値]: {s['第2指値']}円\n\n"
    else:
        mail_body += "該当なし\n\n"

    mail_body += "【AI分析：市場俯瞰】\n" + "="*40 + "\n" + analysis_1 + "\n\n"
    mail_body += "【AI分析：投資戦略】\n" + "="*40 + "\n" + analysis_2
    
    # 送信
    send_report_email(f"【AI分析】本日の初動銘柄レポート ({len(stage1_list)}件)", mail_body)

if __name__ == '__main__':
    run_scanner_final()