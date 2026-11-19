"""One-use loopback key entry. Saving performs no provider request or activation.

Run from the project: python3 tools/configure_research_key.py
Only the local URL/status is printed. Keys, form bodies and headers are not.
"""
import argparse
import hmac
import html
import json
import os
import re
import secrets
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs


class SetupError(ValueError):
    pass


def private_directory(path):
    path = Path(path).absolute()
    for part in reversed([path, *path.parents]):
        if part.is_symlink():
            raise SetupError('Private directory cannot contain a symlink')
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    if path.stat().st_uid != os.getuid():
        raise SetupError('Private directory belongs to a different user')
    path.chmod(0o700)
    return path


def save_key(directory, value, *, replace=False):
    if (not isinstance(value, str) or not re.fullmatch(r'sk-[A-Za-z0-9_-]{20,509}', value)):
        raise SetupError('Invalid key format')
    directory = private_directory(directory)
    path = directory / 'openai.key'
    if path.is_symlink():
        raise SetupError('Key destination cannot be a symlink')
    if path.exists() and not replace:
        raise SetupError('Key already exists; replacement requires explicit selection')
    if path.exists() and (not path.is_file() or path.stat().st_uid != os.getuid()):
        raise SetupError('Invalid existing key destination')
    temporary = directory / ('key-' + secrets.token_hex(16) + '.part')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(value.encode('ascii'))
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            # Atomic no-overwrite, including a concurrent second form/process.
            os.link(temporary, path, follow_symlinks=False)
            temporary.unlink()
        parent = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise SetupError('Key was not saved; existing destination was preserved') from None
    return path


class Form:
    def __init__(self, directory, *, seconds=1800):
        self.directory = Path(directory)
        self.path = '/' + secrets.token_urlsafe(32)
        self.nonce = secrets.token_urlsafe(32)
        self.deadline = time.monotonic() + seconds
        self.saved = False
        self.origin = ''
        self.last_rejection = ''

    def handle(self, method, path, headers, body=b''):
        if (self.saved or time.monotonic() >= self.deadline or path != self.path
                or headers.get('Host') != self.origin.removeprefix('http://')):
            self.last_rejection = 'expired_used_path_or_host'
            return 404, 'Страница ввода недоступна.'
        if method == 'GET':
            return 200, ('<!doctype html><html lang="ru"><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1"><title>Ключ LeadBot</title>'
                '<h1>Локальная настройка API</h1><p>Ключ сохраняется только на этом Mac. '
                'Сохранение не запускает платные запросы, авто или сообщения клиентам.</p>'
                '<form method="post" action="' + html.escape(self.path) + '">'
                '<input type="hidden" name="nonce" value="' + self.nonce + '">'
                '<label>Ключ OpenAI <input type="password" name="key" required minlength="23" maxlength="512" '
                'autocomplete="off" spellcheck="false" size="45"></label><p>'
                '<label><input type="checkbox" name="replace" value="yes">Заменить ранее сохранённый ключ</label></p>'
                '<button type="submit">Сохранить локально</button></form>'
                '<p>Ключ не нужно отправлять в чат. Эта страница не проверяет баланс и доступ к модели.</p></html>')
        # The in-app relay changes Origin (observed rejection category).
        # This cookie-less one-use endpoint uses TWO independent random
        # secrets: an unguessable URL and a per-form nonce. Browser-origin
        # metadata is not the authority; Host + exact path + nonce are.
        # No CORS access is granted, so another site cannot read the nonce.
        if (method != 'POST'
                or headers.get('Content-Type', '').split(';', 1)[0].strip() != 'application/x-www-form-urlencoded'
                or len(body) > 4096):
            self.last_rejection = 'method' if method != 'POST' else 'content_type_or_size'
            return 403, 'Запрос отклонён (' + self.last_rejection + '). Ключ не сохранён.'
        try:
            fields = parse_qs(body.decode('utf-8'), strict_parsing=True, max_num_fields=3)
            if (set(fields) - {'nonce', 'key', 'replace'} or len(fields.get('key', [])) != 1
                    or len(fields.get('nonce', [])) != 1 or len(fields.get('replace', [])) > 1
                    or not hmac.compare_digest(fields['nonce'][0], self.nonce)
                    or fields.get('replace', ['yes'])[0] != 'yes'):
                raise SetupError('Invalid form')
            save_key(self.directory, fields['key'][0], replace=fields.get('replace') == ['yes'])
        except (ValueError, UnicodeError, OSError, TypeError):
            self.last_rejection = 'invalid_form_key_or_existing_destination'
            # Never include an exception, input, key, headers or path in output.
            return 400, 'Ключ не сохранён. Проверьте формат; для замены существующего отметьте замену.'
        self.saved = True
        return 200, 'Ключ сохранён локально. Платные запросы и авто не запускались. Вкладку можно закрыть.'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path,
                        default=Path(__file__).resolve().parents[1] / 'leadbot/data/research-api')
    parser.add_argument('--status', type=Path)
    parser.add_argument('--resume-form', type=Path,
                        help='Private local form nonce/path/port state; contains no API key')
    args = parser.parse_args()
    form = Form(private_directory(args.directory))
    port = 0
    if args.resume_form:
        state = json.loads(args.resume_form.read_text())
        if (not re.fullmatch(r'/[A-Za-z0-9_-]{40,80}', state.get('path', ''))
                or not re.fullmatch(r'[A-Za-z0-9_-]{40,80}', state.get('nonce', ''))
                or type(state.get('port')) is not int or not 1024 <= state['port'] <= 65535):
            raise SetupError('Invalid private local form state')
        form.path, form.nonce, port = state['path'], state['nonce'], state['port']

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def run_form(self):
            try:
                size = int(self.headers.get('Content-Length') or 0)
                if not 0 <= size <= 4096 or self.headers.get('Transfer-Encoding'):
                    code, page = 413, 'Запрос слишком большой.'
                else:
                    code, page = form.handle(self.command, self.path, self.headers,
                                             self.rfile.read(size) if size else b'')
            except (ValueError, OSError):
                code, page = 400, 'Запрос не обработан.'
            raw = page.encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Security-Policy', "default-src 'none'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers()
            self.wfile.write(raw)
            if form.last_rejection:
                status['last_rejection'] = form.last_rejection
                report()

        do_GET = do_POST = run_form

        def handle(self):
            self.connection.settimeout(5)
            try:
                super().handle()
            except (OSError, ValueError):
                pass

    with HTTPServer(('127.0.0.1', port), Handler) as server:
        server.timeout = 1
        form.origin = 'http://127.0.0.1:' + str(server.server_port)
        status = dict(pid=os.getpid(), url=form.origin + form.path, configured=False,
                      paid_calls_started=False, local_only=True)
        def report():
            if args.status:
                path = args.status
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + '\n')
                path.chmod(0o600)
        report()
        print(json.dumps(status, ensure_ascii=False), flush=True)
        try:
            while not form.saved and time.monotonic() < form.deadline:
                server.handle_request()
        finally:
            status.update(configured=form.saved, terminal=True)
            report()
            print(json.dumps(dict(configured=form.saved, terminal=True, paid_calls_started=False)), flush=True)


if __name__ == '__main__':
    main()
