from x.agentplane.capture.llm_recording_proxy import safe_headers


def test_safe_headers_is_header_blind() -> None:
    headers = {
        "Authorization": "Bearer not-for-recording",
        "Cookie": "no",
        "Content-Type": "application/json",
        "X-Trace": "ignored",
    }
    assert safe_headers(headers) == {"content-type": "application/json"}


if __name__ == "__main__":
    import pytest_bazel

    pytest_bazel.main()
