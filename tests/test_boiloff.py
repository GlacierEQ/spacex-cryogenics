import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"src"))
from boiloff import Tank, boiloff_rate_kg_s

def test_positive_boil():
    r = boiloff_rate_kg_s(Tank("LOX", 10, 1000, 90, 300))
    assert r["mdot_kg_s"] > 0

if __name__=="__main__":
    test_positive_boil(); print("ok")
