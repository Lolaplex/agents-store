"""SHA-256 of the on-disk module that implements a wrapper class."""
from __future__ import annotations

import hashlib
import importlib
import inspect
from pathlib import Path

from .contracts import Wrapper


def code_hash_for_class(cls: type) -> str:
    path = Path(inspect.getfile(cls))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def code_hash_for_wrapper(w: Wrapper) -> str:
    return code_hash_for_class(type(w))


def code_hash_for_impl_ref(impl_ref: str) -> str:
    module_path, qualname = impl_ref.rsplit(".", 1)
    mod = importlib.import_module(module_path)
    cls = getattr(mod, qualname)
    return code_hash_for_class(cls)
