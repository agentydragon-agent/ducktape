from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run(
        "ember.app:create_app",
        factory=True,
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )


if __name__ == "__main__":
    main()
