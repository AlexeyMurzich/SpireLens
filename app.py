"""SpireLens: offline, local Python dashboard. Python 3.10+, no dependencies."""
import argparse
import csv
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import threading
import webbrowser
from urllib.parse import parse_qs, urlparse

from analyzer import DEFAULT_ROOT, Store
from exports import csv_cell

STATIC = Path(__file__).parent / 'static'


def make_handler(store):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def send(self, data, content_type='application/json; charset=utf-8', code=200, extra=None):
            if not isinstance(data, bytes):
                data = json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            # Prevent remote websites from reading the local service via DNS rebinding.
            port = self.server.server_port
            if self.headers.get('Host') not in (f'127.0.0.1:{port}', f'localhost:{port}'):
                self.send({'error': 'Недопустимый адрес'}, code=403)
                return
            url = urlparse(self.path)
            query = parse_qs(url.query)
            try:
                if url.path == '/api/meta':
                    self.send(store.metadata())
                elif url.path == '/api/analysis':
                    self.send(store.analysis(query))
                elif url.path.startswith('/api/run/'):
                    result = store.detail(url.path.rsplit('/', 1)[-1])
                    self.send(result or {'error': 'Забег не найден'}, code=200 if result else 404)
                elif url.path == '/api/export.csv':
                    output = io.StringIO(newline='')
                    writer = csv.writer(output, delimiter=';')
                    fields = ['date', 'profile', 'character_name', 'ascension', 'mode', 'coop', 'outcome', 'abandoned', 'floors', 'duration', 'damage', 'deck_size', 'potions_used', 'cause_name', 'seed', 'version']
                    writer.writerow(fields)
                    for run in store.select(query):
                        r = store.brief(run)
                        writer.writerow([csv_cell(r[f]) for f in fields])
                    self.send(output.getvalue().encode('utf-8-sig'), 'text/csv; charset=utf-8',
                              extra={'Content-Disposition': 'attachment; filename="spirelens-runs.csv"'})
                else:
                    files = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'), '/style.css': ('style.css', 'text/css')}
                    if url.path not in files:
                        self.send({'error': 'Страница не найдена'}, code=404)
                    else:
                        name, mime = files[url.path]
                        self.send((STATIC / name).read_bytes(), mime + '; charset=utf-8')
            except (ValueError, OverflowError, OSError) as e:
                self.send({'error': str(e)}, code=400)

    return Handler


def main():
    parser = argparse.ArgumentParser(description='SpireLens — локальная аналитика Slay the Spire 2')
    parser.add_argument('--data-dir', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--pck', type=Path, help='SlayTheSpire2.pck для русских названий')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--check', action='store_true', help='Проверить чтение истории и завершить')
    args = parser.parse_args()
    store = Store(args.data_dir, args.pck)
    store.refresh()
    if args.check:
        meta = store.metadata()
        print(json.dumps(dict(total=meta['total'], profiles=meta['profiles'], errors=meta['errors'], names=meta['names']), ensure_ascii=True, indent=2))
        return
    server = None
    for port in range(args.port, min(args.port + 20, 65536)):
        try:
            server = ThreadingHTTPServer(('127.0.0.1', port), make_handler(store))
            break
        except OSError as e:
            if getattr(e, 'winerror', None) not in (10048, None) or getattr(e, 'errno', None) not in (98, 10048, None):
                raise
    if server is None:
        raise RuntimeError('Нет свободного порта. Запустите с --port 9000')
    stop = threading.Event()
    def watch():
        while not stop.wait(15):
            try:
                store.refresh()
            except OSError:
                pass
    threading.Thread(target=watch, daemon=True).start()
    address = f'http://127.0.0.1:{server.server_port}'
    print(f'SpireLens: {address} | runs: {len(store.runs)}', flush=True)
    if not args.no_browser:
        webbrowser.open(address)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()


if __name__ == '__main__':
    main()
