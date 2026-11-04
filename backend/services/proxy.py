"""Walk a validated forwarded chain from the known direct peer, right to left."""

from ipaddress import ip_address, ip_network

from starlette.requests import Request

from config import get_settings


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    try:
        networks = [
            ip_network(value, strict=False) for value in get_settings().trusted_proxy_list()
        ]
        current = ip_address(peer)
        chain = request.headers.get("x-forwarded-for", "").split(",")
        for value in reversed(chain[-20:]):
            if not any(current in network for network in networks):
                break
            current = ip_address(value.strip())
        return str(current)
    except ValueError:
        return peer
