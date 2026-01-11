@echo off
chcp 65001 > nul
setlocal

echo ===========================================
echo   株価選別システム v1.9 環境セットアップ
echo ===========================================

:: 1. ライブラリのインストール（python -m pip を使用して確実性を向上）
echo [1/2] 必要なライブラリをインストールしています...
python -m pip install --upgrade pip
python -m pip install yfinance pandas tqdm openpyxl

:: 2. 実行用バッチファイルの作成（エラー確認用 pause を完備）
echo [2/2] 実行用のショートカットを作成しています...
(
echo @echo off
echo chcp 65001 ^> nul
echo cd /d "%%~dp0"
echo echo --- 株式分析を開始します ---
echo :: 実行時も python -m を使用して確実に実行
echo python -m scanner
echo echo.
echo echo --------------------------------------
echo 処理が終了しました。画面を閉じるには何かキーを押してください。
echo pause
) > run_scan.bat

echo ===========================================
echo   セットアップが完了しました！
echo   'run_scan.bat' を実行してください。
echo ===========================================
pause