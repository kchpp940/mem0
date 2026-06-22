import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _env_loader import get_env, load_env

load_env()

USER_ID = get_env("MEM0_USER_ID", None) or get_env("USER", "default_user")
DEFAULT_APP_ID = "openmemory"
