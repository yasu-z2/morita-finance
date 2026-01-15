import pickle
import os
from datetime import datetime

CACHE_FILE = 'stock_cache.pkl'

if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE, 'rb') as f:
        cache = pickle.load(f)
    
    print(f"--- キャッシュ内容確認 ({len(cache)} 銘柄) ---")
    print(f"{'コード':<8} | {'最終取得日時':<20} | {'データ行数'}")
    print("-" * 45)
    
    for code, (df, timestamp) in cache.items():
        time_str = timestamp.strftime('%Y-%m-%d %H:%M:%S')
        print(cache['8001.T'][0])
else:
    print("キャッシュファイルが見つかりません。")