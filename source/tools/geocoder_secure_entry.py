"""Single-use loopback entry; existing key goes only to the authorized bot host."""
import hmac
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler,HTTPServer
from urllib.parse import parse_qs
from configure_geocoder_secure import configure

nonce=secrets.token_urlsafe(32)
used=False


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass

    def page(self,text,status=200):
        body=text.encode()
        self.send_response(status)
        self.send_header('Content-Type','text/html; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Security-Policy',"default-src 'none'; form-action 'self'; frame-ancestors 'none'; style-src 'unsafe-inline'")
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)

    def do_GET(self):
        if self.path!='/' or used:return self.page('Закрыто',404)
        self.page('<!doctype html><html lang="ru"><meta charset="utf-8"><title>Сервер LeadBot · Геокодер</title>'
                  '<body style="font:16px system-ui;max-width:620px;margin:48px auto;padding:24px"><h1>Проверка адресов LeadBot</h1>'
                  '<p>Подключение действующего ключа API Геокодера к серверу lead-bot-nl.</p>'
                  '<form method="post" action="/configure"><label>Ключ API Геокодера <input type="password" name="key" autocomplete="off" required></label>'
                  '<input type="hidden" name="nonce" value="'+nonce+'"><button type="submit">Подключить геокодер</button></form>'
                  '<p>Ввод скрыт. Ключ не сохраняется на Mac и не выводится в журнал.</p></body></html>')

    def do_POST(self):
        global used
        origin='http://127.0.0.1:'+str(self.server.server_port)
        if used or self.path!='/configure' or self.headers.get('Origin') not in (None,'null',origin) or self.headers.get('Host')!=origin.removeprefix('http://'):
            return self.page('Запрос отклонён',403)
        size=int(self.headers.get('Content-Length','0'))
        if not 0<size<4096:return self.page('Запрос отклонён',400)
        values=parse_qs(self.rfile.read(size).decode())
        if not hmac.compare_digest(values.get('nonce',[''])[0],nonce):return self.page('Запрос отклонён',403)
        key=values.get('key',[''])[0].strip()
        try:
            result=configure(key)
            used=True
            print(json.dumps(result),flush=True)
            self.page('<!doctype html><html lang="ru"><meta charset="utf-8"><title>Геокодер подключён</title><body style="font:18px system-ui;padding:48px"><h1>Геокодер подключён</h1><p>Действующий ключ сохранён на сервере lead-bot-nl. Значение ключа не выводилось в журнал.</p><p>Автоматический режим LeadBot не включался.</p></body></html>')
            threading.Thread(target=self.server.shutdown,daemon=True).start()
        except Exception:
            self.page('Подключение не завершено; значение ключа скрыто',502)
        finally:
            key='';values.clear()


server=HTTPServer(('127.0.0.1',0),Handler)
print(json.dumps({'listen_port':server.server_port,'key_logged':False,'loopback_only':True}),flush=True)
server.serve_forever()
server.server_close()
