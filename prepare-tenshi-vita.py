"""Prepare the user's local PC resources; --build also makes the matching Vita release."""
from pathlib import Path
import sys

from vita_asset_pipeline.cli import main

if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main(Path(__file__).resolve().parent))
