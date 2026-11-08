"""Pull the Part 6 interview Q&A out of STUDY-GUIDE.md into qa.json for the deck."""

import json
import re
import sys
from pathlib import Path

s = Path(sys.argv[1]).read_text(encoding="utf-8")
part = s[s.index("# Part 6.") : s.index("# Part 7.")]
cats = []
for block in re.split(r"\n## ", part)[1:]:
    title, body = block.split("\n", 1)
    qs = re.findall(r"\*\*(\d+)\. (.+?)\*\*\n(.+?)(?=\n\n|\Z)", body, re.S)
    cats.append(
        {
            "title": title.strip(),
            "qs": [{"n": int(n), "q": q.strip(), "a": " ".join(a.split())} for n, q, a in qs],
        }
    )
Path(sys.argv[2]).write_text(json.dumps(cats, indent=1))
