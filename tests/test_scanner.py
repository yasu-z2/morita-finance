import os
from scanner import generate_final_report, HISTORY_PERIOD, WINDOW_DAYS


def test_constants():
    assert isinstance(HISTORY_PERIOD, str)
    assert isinstance(WINDOW_DAYS, int)


def test_missing_csv(tmp_path, capsys):
    missing = tmp_path / "no_file.csv"
    assert not missing.exists()
    res = generate_final_report(str(missing))
    captured = capsys.readouterr()
    assert "エラー: 指定したファイルが見つかりません" in captured.out or res is None
