:: 1. ローカルリポジトリを初期化 (まだ一度も行っていない場合)
git init

:: 2. すべてのファイルをステージング（追加）
git add .

:: 3. コミット（変更内容の記録）
git commit -m "全機能統合・2段階AI選別版 (v3.0.4)"

:: 4. メインブランチの名前を main に設定
git branch -M main

:: 5. リモートリポジトリ（GitHub上のURL）を登録
:: ※ [ユーザー名] と [リポジトリ名] は、あなたのGitHubに合わせて書き換えてください
git remote add origin https://github.com/yasu-z2/mirota-finance.git

:: 6. GitHubへアップロード
git push -u origin main