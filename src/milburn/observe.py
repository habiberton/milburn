
from uuid_utils import uuid4


def make_run_id() -> str:
    return f"run_{uuid4()}"