from fastapi.testclient import TestClient

from proxy_forge.app import create_app
from proxy_forge.engine import Engine
from studio_kit.clerk_auth import ClerkVerifier


def client(clerk=None, token=None):
    return TestClient(create_app(Engine(start=False), clerk=clerk, tunnel_token=token))


TUNNEL = {"host": "proxies.example.com", "cf-connecting-ip": "1.2.3.4"}


def test_home_machine_needs_no_sign_in():
    assert client().get("/api/templates").status_code == 200


def test_tunnel_is_refused_outright_when_nothing_is_configured():
    c = client()
    assert c.get("/api/templates", headers=TUNNEL).status_code == 403
    assert c.get("/", headers=TUNNEL).status_code == 200                      # the page holds no secret
    assert c.get("/app-config.json", headers=TUNNEL).status_code == 200


def test_tunnel_with_clerk_wants_a_valid_token_of_an_allowed_user():
    clerk = ClerkVerifier("https://x.clerk.accounts.dev", {"user_1"})
    c = client(clerk)
    assert c.get("/api/templates", headers=TUNNEL).status_code == 401
    assert c.get("/api/templates", headers={**TUNNEL, "authorization": "Bearer a.b.c"}).status_code in (401, 503)     # forged / keys unreachable: never allowed
    assert c.get("/api/decks", headers={**TUNNEL, "authorization": "Bearer nonsense"}).status_code == 401
    assert c.get("/api/templates").status_code == 200                          # still open at home


def test_script_secret_lets_a_tunnel_request_in():
    c = client(token="s3cret")
    assert c.get("/api/templates", headers={**TUNNEL, "authorization": "Bearer s3cret"}).status_code == 200
    assert c.get("/api/templates", headers={**TUNNEL, "authorization": "Bearer wrong"}).status_code == 401


def test_a_proxy_header_alone_counts_as_the_internet():
    c = client()
    assert c.get("/api/templates", headers={"x-forwarded-for": "9.9.9.9"}).status_code == 403
