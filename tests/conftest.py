"""Le due serie di prove usano due configurazioni diverse (le costanti di config.py si leggono all'import), quindi non
possono girare nello stesso processo di pytest:
  JEFF_TEST_SUITE=jeff (default)  tests/test_jeff.py     configurazione vera di jeff-coach (multi-edge + Jeff)
  JEFF_TEST_SUITE=base            tests/test_offline.py  base di Martin con le regole di Dua (prove di identità)
Senza pytest: python tests/test_jeff.py  e  python tests/test_offline.py."""
import os

collect_ignore = ["test_offline.py"] if os.environ.get("JEFF_TEST_SUITE", "jeff") == "jeff" else ["test_jeff.py"]
