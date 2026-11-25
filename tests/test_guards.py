import pytest

from fullshot.capture import CaptureError, check_cdp_url, is_private_host, validate_url


def test_scheme_rules():
    assert validate_url("example.com", False) == "https://example.com"
    with pytest.raises(CaptureError):
        validate_url("file:///etc/passwd", False)
    with pytest.raises(CaptureError):
        validate_url("javascript:alert(1)", False)
    assert validate_url("file:///tmp/a.html", True).startswith("file:")


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "10.1.2.3", "192.168.0.1", "169.254.169.254", "::1"])
def test_private_hosts(host):
    assert is_private_host(host)


def test_public_ip():
    assert not is_private_host("8.8.8.8")


def test_cdp_must_be_local(monkeypatch):
    check_cdp_url("http://127.0.0.1:9222")
    monkeypatch.delenv("FULLSHOT_ALLOW_REMOTE_CDP", raising=False)
    with pytest.raises(CaptureError):
        check_cdp_url("http://evil.example:9222")
