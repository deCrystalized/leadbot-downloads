import sys
from pathlib import Path
from http.server import ThreadingHTTPServer
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'leadbot/brain'))
import server
class Handler(server.Handler):
 def log_message(self,*args):pass
ThreadingHTTPServer(('127.0.0.1',8789),Handler).serve_forever()
