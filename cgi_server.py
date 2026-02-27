#!/usr/bin/env python
"""
Simple server for running the neutron activation calculator.

This is intended for testing.  It has not been assessed for security and is
not recommended for a public facing server.  The activation calculator
expects a cgi interface, which should be provided by the web infrastructure
(apache, nginx, etc.) that you are using on your production server.

Usage: python server.py [host | host:port]

Default is localhost:8008
"""

from __future__ import print_function

import re
import sys
import os
try:
    from http.server import HTTPServer, CGIHTTPRequestHandler
    from socketserver import ThreadingMixIn
except ImportError:
    from BaseHTTPServer import HTTPServer
    from SocketServer import ThreadingMixIn
    from CGIHTTPServer import CGIHTTPRequestHandler
import cgitb
cgitb.enable()  ## This line enables CGI error reporting

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Very simple threaded server"""
    allow_reuse_address = True
    request_queue_size = 50

# ==========================================
# NEW: Custom Handler to intercept index.html
# ==========================================
class CustomCGIHTTPRequestHandler(CGIHTTPRequestHandler):
    def do_GET(self):
        # Intercept requests exactly matching the index route
        if self.path in ('/activation/', '/activation/index.html'):

            # self.translate_path converts the URL path to a local OS file path
            file_path = self.translate_path('/activation/index.html')

            try:
                # Read the original file
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                pattern = re.compile(r'src="api_[a-zA-Z_-]+.js"', re.IGNORECASE)
                replacement = 'src="api_cgi.js"'

                # Perform the substitution
                modified_content = pattern.sub(replacement, content)

                # Convert the string back to bytes for transport
                encoded_content = modified_content.encode('utf-8')

                self.send_response(200)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded_content)))
                self.end_headers()
                self.wfile.write(encoded_content)

            except (IOError, OSError):
                self.send_error(404, "File not found")
        else:
            # For everything else (CGI scripts, CSS, JS, images), use the default behavior
            CGIHTTPRequestHandler.do_GET(self)

server = ThreadedHTTPServer
handler = CustomCGIHTTPRequestHandler
handler.cgi_directories = ["/cgi-bin"]

if len(sys.argv) > 1:
    host, *rest = sys.argv[1].split(':', 1)
    port = int(rest[0]) if rest else 8008
else:
    host, port = "localhost", 8008
print(f"serving on http://{host}:{port}/activation/")
httpd = server((host, port), handler)
httpd.serve_forever()
