@echo off
setlocal
echo ===========================================
echo   株価選別システム v1.9 環境セットアップ
echo ===========================================

:: 1. 必要なライブラリのインストール
echo [1/2] 必要なライブラリ(yfinance等)をインストールしています...
pip install yfinance pandas tqdm openpyxl

:: 2. 実行用バッチファイルの作成
echo [2/2] 実行用のショートカットを作成しています...
(
echo @echo off
echo cd /d "%%~dp0"
echo echo --- 株式分析を開始します ---
echo python scanner.py
echo pause
) > run_scan.bat

echo ===========================================
echo   セットアップが完了しました！
echo.
echo   【使い方】
echo   1. 同じフォルダに 'data_jpx.csv' があることを確認してください。
echo   2. 'run_scan.bat' をダブルクリックすると実行されます。
echo ===========================================
pause