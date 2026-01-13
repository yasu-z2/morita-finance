# ==========================================================
# プログラム名: 株価選別システム (GitHub Actions 疎通確認版)
# バージョン: 3.0.1 (STEP1: 配信テスト)
# 更新日: 2026-01-13
# 概要: 
#   - GitHub Actions 上で正常に Python が動作するか確認
#   - GitHub Secrets の環境変数が正しく読み込まれるか確認
#   - メール送信の成功を確認（Gemini API は負荷軽減のため未使用）
# ==========================================================

import os
import smtplib
from email.mime.text import MIMEText
from email.utils import formatdate
from datetime import datetime

# --- 環境変数 (GitHub Secretsから自動取得) ---
MAIL_ADDRESS   = os.environ.get('MAIL_ADDRESS')
MAIL_PASSWORD  = os.environ.get('MAIL_PASSWORD')
TO_ADDRESS     = os.environ.get('TO_ADDRESS')

def send_report_email(subject, body):
    """シンプルなメール送信関数"""
    if not MAIL_ADDRESS or not MAIL_PASSWORD:
        print("Error: MAIL_ADDRESS or MAIL_PASSWORD is not set in Secrets.")
        return

    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = MAIL_ADDRESS
    msg['To'] = TO_ADDRESS
    msg['Date'] = formatdate(localtime=True)

    try:
        # GmailのSMTPサーバー設定
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(MAIL_ADDRESS, MAIL_PASSWORD)
        server.send_message(msg)
        server.close()
        print(">>> GitHub Actions からのメール送信に成功しました。")
    except Exception as e:
        print(f">>> メール送信中にエラーが発生しました: {e}")

def main():
    """STEP1のメイン処理"""
    now_str = datetime.now().strftime('%Y/%m/%d %H:%M:%S')
    
    # メールの本文作成
    mail_body = f"""■ GitHub Actions 実行テストレポート (STEP1)
============================================================
実行時刻 (JST): {now_str}
ステータス: 成功
============================================================

このメールは GitHub Actions の自動実行によって送信されています。

【確認事項】
1. Python スクリプトの実行：OK
2. 環境変数の読み込み：OK
3. SMTP 認証とメール送信：OK

このテストが成功したため、次は全銘柄スキャンの時間計測（STEP2）へ
進む準備が整いました。

※このステップでは Gemini API へのリクエストは行っていません。
============================================================"""
    
    send_report_email(f"【疎通確認】GitHub Actions 実行成功 ({now_str})", mail_body)

if __name__ == '__main__':
    main()