from adgn_llm.mcp.public_git.server import UrlKey


def test_urlkey_github_https_mapping():
    k = UrlKey(origin_url="https://github.com/org/repo.git")
    assert k.host == "github.com"
    assert k.path == "org/repo"
    assert k.storage_key_gitea == "org/repo.git"
    assert k.pretty == "github.com/org/repo"


def test_urlkey_generic_http_mapping():
    k = UrlKey(origin_url="http://example.com/a/b/c.git")
    assert k.host == "example.com"
    assert k.path == "a/b/c"
    assert k.storage_key_gitea == "b/c.git"  # last two path segments
    assert k.pretty == "example.com/a/b/c"
