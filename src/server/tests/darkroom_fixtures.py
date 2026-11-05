"""Real RAW fixtures for the Web Darkroom tests. Private photos never go into git:
point MFILM_TEST_DNG / MFILM_TEST_NEF at files, or the defaults below are used; tests skip when absent."""
import os
from pathlib import Path

CALIB = Path("/mnt/theVault/Archives/roshal_old_photos/mfilm_calibration")
DNG = Path(os.environ.get("MFILM_TEST_DNG") or CALIB / "CRW_4211.DNG")
DNG2 = Path(os.environ.get("MFILM_TEST_DNG2") or CALIB / "CRW_4212.DNG")
NEF = Path(os.environ["MFILM_TEST_NEF"]) if os.environ.get("MFILM_TEST_NEF") else None
CR2 = Path(__file__).resolve().parents[3] / "vendor/m-film/ml-dev/films/sample/SAMPLE.CR2"
