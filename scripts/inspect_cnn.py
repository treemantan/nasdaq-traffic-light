import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from market_report.data_sources import _read_text

s = _read_text("https://edition.cnn.com/markets/fear-and-greed", timeout=15)
for term in ["fearGreed", "fear-and-greed", "fear_greed", "market_momentum", "fearGreedIndex", "fearAndGreed"]:
    print(term, s.find(term))

for pattern in [
    r'"score"\s*:\s*66',
    r'score.{0,100}66',
    r'66.{0,100}Greed',
    r'Greed.{0,100}66',
]:
    print("PATTERN", pattern)
    for m in re.finditer(pattern, s, re.I | re.S):
        print(m.start(), s[m.start() - 100:m.start() + 300].encode("unicode_escape").decode())
        break
