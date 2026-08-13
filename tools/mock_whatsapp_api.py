#!/usr/bin/env python3
from http.server import HTTPServer, BaseHTTPRequestHandler
import json

class Handler(BaseHTTPRequestHandler):
    def _send(self, code, data):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def do_POST(self):
        if self.path != '/send':
            self._send(404, {'error': 'not found'})
            return
        length = int(self.headers.get('Content-Length', '0'))
        body = self.rfile.read(length).decode('utf-8') if length else ''
        try:
            payload = json.loads(body) if body else {}
        except Exception:
            payload = {}
        contact = payload.get('contact_name') or payload.get('contact') or payload.get('to')
        message = payload.get('message') or payload.get('text')
        # Simulate acceptance
        resp = {
            'status': 'accepted',
            'contact': contact,
            'message': message,
            'message_id': 'mockmsg123'
        }
        self._send(202, resp)

    def log_message(self, format, *args):
        # Keep server quiet
        return

if __name__ == '__main__':
    server = HTTPServer(('127.0.0.1', 5005), Handler)
    print('Mock WhatsApp API listening on http://127.0.0.1:5005/send')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
        print('Server stopped')
