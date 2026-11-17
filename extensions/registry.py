

import importlib
import pkgutil
from pathlib import Path


class Registry:
    def __init__(self):
        self.sources: dict = {}
        self.strategies: dict = {}
        self.metrics: dict = {}
        self.reporters: dict = {}
        self._discovered = False

    # ---- decorators ------------------------------------------------

    def source(self, name: str):
        def deco(fn):
            self.sources[name] = fn
            return fn
        return deco

    def strategy(self, name: str):
        def deco(fn):
            self.strategies[name] = fn
            return fn
        return deco

    def metric(self, name: str):
        def deco(fn):
            self.metrics[name] = fn
            return fn
        return deco

    def reporter(self, name: str):
        def deco(fn):
            self.reporters[name] = fn
            return fn
        return deco

    # ---- discovery -------------------------------------------------

    def discover(self) -> None:
        if self._discovered:
            return
        for cat in ("sources", "strategies", "metrics", "reporters"):
            pkg_name = f"extensions.{cat}"
            try:
                package = importlib.import_module(pkg_name)
            except ImportError:
                continue
            for _, mod_name, _ in pkgutil.iter_modules(package.__path__):
                importlib.import_module(f"{pkg_name}.{mod_name}")
        self._discovered = True

    # ---- introspection --------------------------------------------

    def summary(self) -> dict:
        return {
            "sources": sorted(self.sources),
            "strategies": sorted(self.strategies),
            "metrics": sorted(self.metrics),
            "reporters": sorted(self.reporters),
        }


REGISTRY = Registry()