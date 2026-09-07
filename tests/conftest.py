import socket
import pytest

class BlockedNetworkAccess(OSError):
    pass

def _blocked_connect(*args, **kwargs):
    raise BlockedNetworkAccess("Network access is blocked during tests — mock external calls instead.")

@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _blocked_connect)
