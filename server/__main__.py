"""Dev server entrypoint: `python -m server` (uWSGI is used in Docker)."""
from server import app

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000, debug=True)
