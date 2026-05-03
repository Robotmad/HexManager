__all__ = ["HexManagerApp"]


def __getattr__(name):
	if name == "HexManagerApp":
		from .app import HexManagerApp
		return HexManagerApp
	raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
