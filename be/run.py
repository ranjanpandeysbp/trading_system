import os

import uvicorn

if __name__ == "__main__":
    # Default: single process (avoids orphan reloaders on Windows when restarting).
    # Set RELOAD=1 for auto-reload during development.
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=2009,
        reload=os.getenv("RELOAD", "0") == "1",
    )
