import socket
import sys

from app import create_app

HOST = "127.0.0.1"
PORT = 5000


def _port_already_serving():
    """True if something is already listening on our host/port.

    Werkzeug's dev server binds with SO_REUSEADDR, so on Windows a second
    backend can silently share 127.0.0.1:5000 with the first - two processes
    then write the same SQLite file through separate WALs, which can lose
    data. The Electron layer already enforces a single app instance; this is
    a second line of defence so a stray manual launch fails loudly instead of
    quietly double-binding.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((HOST, PORT)) == 0


app = create_app()

if __name__ == "__main__":
    if _port_already_serving():
        print(
            f"Another backend is already listening on {HOST}:{PORT}; refusing "
            f"to start a second instance.",
            file=sys.stderr,
        )
        sys.exit(1)
    app.run(host=HOST, port=PORT, debug=False)
