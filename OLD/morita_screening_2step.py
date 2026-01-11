# ============================================
# morita_screening_2step.py
# Version: v2.5-shuffle500-hitcheck
# CSVシャッフル → 冒頭500件 → HIT確認用
# ============================================

import yfinance as yf
import pandas as pd
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import random

# ========= 設定 =========
TARGET_CODES_FILE = "tse_prime_codes.csv"   # ヘッダーなし
MAX_TEST = 500
PRICE_LIMIT = 2000
OUTPUT_CSV = "screening_hits_shuffle500.csv"
THREADS = 8
RANDOM_SEED = 42
# ========================


def is_etf_or_reit(code: str) -> bool:
    base = code.replace(".T", "")
    if not base.isdigit():
        return True
    b = int(base)
    return (
        1300 <= b <= 1399 or
        1500 <= b <= 1699 or
        2000 <= b <= 2999 or
        3300 <= b <= 3399
    )


def fetch_price(code: str):
    try:
        df = yf.download(
            f"{code}.T",
            period="3mo",
            interval="1d",
            progress=False,
            threads=False
        )
        if df is None or df.empty:
            return None, "取得失敗"
        if not {"Close", "Volume"}.issubset(df.columns):
            return None, "カラム不足"
        df = df.dropna()
        if len(df) < 30:
            return None, "データ不足"
        return df, None
    except Exception:
        return None, "取得失敗"


def stage1_filter(code):
    if is_etf_or_reit(code):
        return None, "ETF/REIT除外"

    df, err = fetch_price(code)
    if err:
        return None, err

    close_today = float(df["Close"].iloc[-1])
    if close_today > PRICE_LIMIT:
        return None, "株価超過"

    return df, None


def stage2_filter(code, df):
    close = df["Close"].tail(25)
    volume = df["Volume"].tail(25)

    low_25 = float(close.min())
    close_today = float(close.iloc[-1])

    if not (low_25 * 0.9 <= close.min() <= low_25 * 1.1):
        return None, "底値乖離"

    if close_today < low_25 * 1.1:
        return None, "上昇率不足"

    vol_avg = float(volume.mean())
    if not (volume.iloc[-1] >= vol_avg * 2 and volume.iloc[-2] >= vol_avg * 2):
        return None, "出来高不足"

    return {
        "code": f"{code}.T",
        "close": round(close_today, 2),
        "volume": int(volume.iloc[-1])
    }, None


def main():
    start = datetime.now()
    print("▶ 開始:", start.strftime("%Y-%m-%d %H:%M:%S"))
    print("▶ 検証方法: CSVシャッフル → 冒頭500件")

    # --- 銘柄ロード ---
    codes = pd.read_csv(TARGET_CODES_FILE, header=None)[0].astype(str).tolist()
    codes = [c.replace(".T", "") for c in codes]

    random.seed(RANDOM_SEED)
    random.shuffle(codes)
    codes = codes[:MAX_TEST]

    err1 = {}
    err2 = {}
    stage1_pass = []

    print("\n--- 第1段階（並列）---")
    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        futures = {ex.submit(stage1_filter, c): c for c in codes}
        for i, f in enumerate(as_completed(futures), 1):
            df, e = f.result()
            if e:
                err1[e] = err1.get(e, 0) + 1
            else:
                stage1_pass.append((futures[f], df))
            if i % 50 == 0 or i == len(codes):
                print(f"  進捗: {i}/{len(codes)}")

    print(f"▶ 第1段階通過: {len(stage1_pass)}")

    print("\n--- 第2段階 ---")
    hits = []
    for code, df in stage1_pass:
        res, e = stage2_filter(code, df)
        if e:
            err2[e] = err2.get(e, 0) + 1
        else:
            print(f"✅ HIT {res['code']} {res['close']}")
            hits.append(res)

    pd.DataFrame(hits).to_csv(
        OUTPUT_CSV, index=False, encoding="utf-8-sig"
    )

    end = datetime.now()
    print("\n▶ 終了:", end.strftime("%Y-%m-%d %H:%M:%S"))
    print("⏱ 処理時間:", end - start)

    print("\n--- 第1段階除外 ---")
    for k, v in err1.items():
        print(f"{k}: {v}")

    print("\n--- 第2段階除外 ---")
    for k, v in err2.items():
        print(f"{k}: {v}")

    print(f"\n✅ ヒット数: {len(hits)}")
    print(f"📄 CSV保存: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
