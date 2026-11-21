"""Technical notes for the TCI audio link, saved for troubleshooting."""

from datetime import datetime
import os
from pathlib import Path

LOG = (Path(os.getenv("LOCALAPPDATA") or Path.home()) / "CW_Rig_Desk" / "tci-audio.log")
LIMIT = 512 * 1024


def note(message):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        if LOG.exists() and LOG.stat().st_size > LIMIT:
            LOG.replace(LOG.with_suffix(".old.log"))
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}\n")
    except OSError:
        pass
