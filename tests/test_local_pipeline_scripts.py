from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_full_local_pipeline_bat_invokes_pipeline_script() -> None:
    bat = ROOT / "run_full_local_pipeline.bat"

    text = bat.read_text(encoding="utf-8")

    assert "scripts\\run_full_local_pipeline.ps1" in text


def test_full_local_pipeline_downloads_ibkr_and_imports_all_statements() -> None:
    script = ROOT / "scripts" / "run_full_local_pipeline.ps1"

    text = script.read_text(encoding="utf-8")

    assert "scripts\\download_ibkr_flex.py" in text
    assert "scripts\\import_portfolio_statements.py" in text
    assert ".cloud-statements" in text
    assert "IBKR_FLEX_TOKEN" in text
