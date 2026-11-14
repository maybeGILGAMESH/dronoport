"""Запуск воспроизводимой подготовки данных из корня проекта."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from droneport.ingest import run

if __name__ == "__main__":
    run()
