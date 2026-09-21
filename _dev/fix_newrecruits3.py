import sys, json, importlib
sys.path.insert(0, 'H:/KenshiModTranslate')

# --- injected by move_to_dev: let us import core modules from parent ---
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
# --- end injected prologue ---

import verify_translations as VT
importlib.reload(VT)
import validate_translation as V
state = 'H:/KenshiMo...[truncated]