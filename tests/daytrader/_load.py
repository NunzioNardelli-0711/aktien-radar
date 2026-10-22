"""Lädt die übernommenen Werkzeuge für die Original-Tests aus radar/vendor/daytrader."""

import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
FIX = os.path.join(HERE, "fixtures")
VENDOR = os.path.join(ROOT, "radar", "vendor", "daytrader")


def load(folder, name):
    """folder (z. B. "trader-scanner") bleibt aus Kompatibilität mit den Original-Tests erhalten."""
    path = os.path.join(VENDOR, name + ".py")
    spec = importlib.util.spec_from_file_location("trader_" + name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
