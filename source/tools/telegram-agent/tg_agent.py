"""Telegram для лид-центра — программа для компьютера, где работает Telegram.

Зачем: из Yandex Cloud Telegram недоступен. Эта программа держит связь с Telegram от вашего личного
аккаунта и выполняет задания расширения «LeadChat → Заявка в CRM», которые передаёт сервер команды:
отправить заявку на согласование в чат города, прочитать ответы, обновить список групп, сводка по чатам.

Запуск на Windows: двойной щелчок по «Запустить Telegram для лид-центра.bat» (рядом с этим файлом).
Запуск на Mac (Терминал):  python3 tg_agent.py
  Первый раз спросит api_id / api_hash (my.telegram.org), номер телефона и код из Telegram.
  Потом предложит запускаться сама при включении компьютера (Windows — «Автозагрузка», Mac — launchd).
  tg_agent.py --autostart     — включить автозапуск
  tg_agent.py --no-autostart  — выключить автозапуск и остановить фоновую программу
  tg_agent.py --logout        — забыть вход (сессию) на этом компьютере
  tg_agent.py --proxy         — указать прокси (tg-ws-proxy: секрет из его настроек, 127.0.0.1:1443)

Вход хранится только на этом компьютере: ~/.lead-centre-tg/config.json (доступ только у вашей учётной записи).
Там же ключ программы для сервера команды (agent_token): его даёт ведущий, в этом файле его нет.
  tg_agent.py --token         — вставить новый ключ программы («Вставить ключ программы.bat»)
Программа отправляет только то, что просит расширение, и только в группы вашего аккаунта.
Сводка по чатам (--scan) — обезличенная: телефоны, адреса и имена клиентов скрыты.
"""
import asyncio
import getpass
import json
import os
import platform
import re
import subprocess
import sys
import time
import traceback
import warnings

# MTProto-прокси (tg-ws-proxy) работает без python-socks — предупреждение Telethon про него не относится к делу
warnings.filterwarnings("ignore", message="proxy argument will be ignored")

HOME = os.path.expanduser("~/.lead-centre-tg")
VENV = HOME
CONFIG = os.path.join(HOME, "config.json")
# 2.0.5: сервер команды — на своём сервере (Yandex Cloud Functions лежали 11–12.10). Другой адрес — «team_url» в config.json
TEAM_URL = "https://72-56-99-103.sslip.io/team"
_АДРЕС = {"url": None}


def адрес_сервера():
    if _АДРЕС["url"] is None:
        свой = str(load_cfg().get("team_url") or "").strip()
        _АДРЕС["url"] = свой if re.match(r"^https://[A-Za-z0-9.\-]+(:\d+)?(/[A-Za-z0-9._\-/]*)?$", свой) else TEAM_URL
    return _АДРЕС["url"]
# 2.0.0: ключ программы для сервера команды — не в этом файле (старый общий токен отозван), а в config.json
# этого компьютера, строка "agent_token". Сменить: tg_agent.py --token («Вставить ключ программы.bat»).
AGENT_TOKEN = ""
ВЕРСИЯ_ПРОГРАММЫ = "2.0.8"
PLIST = os.path.expanduser("~/Library/LaunchAgents/ru.leadcentre.tgagent.plist")
LOG = os.path.join(HOME, "agent.log")
PIDFILE = os.path.join(HOME, "agent.pid")
WIN = sys.platform.startswith("win")
# Windows: «Автозагрузка» текущего пользователя
STARTUP_VBS = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "Startup", "Lead-centre Telegram.vbs")


def win_python():
    # чем запускать в фоне на Windows: pythonw.exe (если есть) или python.exe — окно всё равно скрыто
    cands = [os.path.join(VENV, "Scripts", "pythonw.exe"), os.path.join(os.path.dirname(sys.executable), "pythonw.exe"),
             os.path.join(VENV, "Scripts", "python.exe"), sys.executable]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return sys.executable


def venv_python(windowless=False):
    if WIN:
        return os.path.join(VENV, "Scripts", "pythonw.exe" if windowless else "python.exe")
    return os.path.join(VENV, "bin", "python")

try:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.errors import SessionPasswordNeededError
    import certifi
except ImportError:
    # своя папка с библиотеками (на Mac с Homebrew ставить в систему нельзя; на Windows так проще обновлять)
    py = venv_python()
    if os.path.realpath(sys.prefix) == os.path.realpath(VENV):
        raise                                   # уже в своей папке, а библиотек нет — показать ошибку
    if not os.path.exists(py):
        print("Создаю папку", VENV, "(один раз)…")
        subprocess.check_call([sys.executable, "-m", "venv", VENV])
    if subprocess.call([py, "-c", "import telethon, certifi"], stderr=subprocess.DEVNULL) != 0:
        print("Ставлю библиотеки telethon и certifi (один раз, нужен интернет)…")
        subprocess.check_call([py, "-m", "pip", "install", "--quiet", "telethon==1.45.0", "certifi"])
    if WIN:                                     # на Windows execv не заменяет процесс — запускаем и ждём
        sys.exit(subprocess.call([py] + sys.argv))
    os.execv(py, [py] + sys.argv)

import ssl
import urllib.error
import urllib.parse
import urllib.request

SSL = ssl.create_default_context(cafile=certifi.where())


def log(*a):
    line = time.strftime("%d.%m %H:%M:%S") + " " + " ".join(str(x) for x in a)
    try:
        if sys.stdout:
            print(line, flush=True)
    except Exception:
        pass
    try:
        os.makedirs(HOME, exist_ok=True)
        if os.path.exists(LOG) and os.path.getsize(LOG) > 2_000_000:          # журнал не разрастается
            os.replace(LOG, LOG + ".old")
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ---------- сервер команды ----------
class KeyRejected(RuntimeError):
    """сервер не принял ключ программы: переподключать Telegram бессмысленно — ждём новый ключ (config.json)"""


КЛЮЧ_НЕ_ПРИНЯТ = "Ключ программы не принят — запустите «Вставить ключ программы.bat»"
TG_НЕ_ПОДКЛЮЧЁН = "Программа на компьютере запущена, но Telegram не подключается: запустите tg-ws-proxy/VPN"


def team(op, body=None, **q):
    url = адрес_сервера() + "?op=" + op + "".join("&%s=%s" % (k, urllib.parse.quote(str(v))) for k, v in q.items())
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET",
                                 headers={"X-Agent-Token": AGENT_TOKEN, "X-Team-User": "tg-agent", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30, context=SSL) as r:
            return r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 403:
            try:
                txt = e.read().decode("utf-8", "replace")[:200]
            except Exception:
                txt = ""
            if "нужен токен мозга" in txt:          # ключ подошёл, но старый сервер не знает эту операцию
                raise RuntimeError("сервер команды не знает операцию %s — обновите на нём index.py" % op)
            raise KeyRejected("сервер не принял ключ программы — вставьте новый: «Вставить ключ программы.bat» (tg_agent.py --token)")
        # не «нет связи с Telegram»: HTTPError — это OSError, и раньше ответ сервера команды выдавался за обрыв Telegram
        raise RuntimeError("сервер команды ответил ошибкой %s — повтор сам" % e.code)


# что сообщаем серверу при опросе: ok — Telegram подключён; tg_down — программа жива, а Telegram нет (why: proxy|net|auth).
# В tg_down сервер заданий не выдаёт и пишет оператору, что запустить. sent — что сервер уже знает (смена — chg=1, сразу)
СВЯЗЬ = {"state": "ok", "why": "", "sent": "", "key_bad": False}


def poll():
    st, why = СВЯЗЬ["state"], СВЯЗЬ["why"]
    q = {"name": platform.node()[:40], "state": st}
    if st != "ok":
        q["why"] = why
    if СВЯЗЬ["sent"] != st + why:
        q["chg"] = "1"
    r = team("agent_poll", None, **q)
    СВЯЗЬ["sent"] = st + why
    return r


async def пульс():
    # Telegram не подключается: раз в 10 с отмечаемся на сервере с state=tg_down — оператор видит не «компьютер не на связи»,
    # а «запустите tg-ws-proxy/VPN», и задание не ставится в очередь зря
    while True:
        try:
            r = json.loads(await asyncio.to_thread(poll))
            for job in r.get("jobs", []):            # старый сервер ещё выдаёт задания и в tg_down — сразу «не выполнено»
                await asyncio.to_thread(team, "agent_done", {"id": job["id"], "error": TG_НЕ_ПОДКЛЮЧЁН})
        except KeyRejected:
            СВЯЗЬ["key_bad"] = True
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(10)


class ConsoleInputUnavailable(RuntimeError):
    """Ручной ввод недоступен; это не отказ Telegram и не повод стирать вход."""


def доступен_ручной_ввод():
    try:
        if sys.stdin is not None and sys.stdin.isatty():
            return True
    except (OSError, ValueError):
        pass
    if WIN:
        try:
            with open("CONIN$", "r", encoding="utf-8") as console:
                return console.isatty()
        except (OSError, ValueError):
            pass
    return False


def ввод_строки(подсказка):
    # py.exe/venv могут унаследовать stdin с установленным EOF. Не читаем
    # файлы/каналы вместо консоли; для Windows ровно один новый CONIN$.
    if sys.stdout is None:
        raise ConsoleInputUnavailable("Окно для ручного ввода не открыто.")
    try:
        обычный = sys.stdin is not None and sys.stdin.isatty()
    except (OSError, ValueError):
        обычный = False
    if обычный:
        try:
            return input(подсказка)
        except (EOFError, OSError, ValueError):
            pass
    if WIN:
        try:
            with open("CONIN$", "r", encoding="utf-8") as console:
                if not console.isatty():
                    raise OSError("Not an interactive console")
                print("\n" + подсказка, end="", flush=True)
                строка = console.readline()
                if строка:
                    return строка.rstrip("\r\n")
        except (OSError, ValueError):
            pass
    raise ConsoleInputUnavailable(
        "Консоль перестала принимать ввод. Закройте это окно и запустите "
        "«ЗАПУСК 2.0.8 — нажать сюда.bat» из распакованной папки. "
        "Сохранённые настройки и вход не удаляйте.")


def без_консоли():
    # автозапуск (pythonw, окна нет) — сообщение в журнале никто не увидит
    try:
        return sys.stdout is None or not доступен_ручной_ввод()
    except Exception:
        return True


def окно(text):
    # Windows: окно с сообщением поверх остальных; программа тем временем ждёт дальше (отдельный поток)
    if not WIN:
        return
    try:
        import ctypes
        import threading
        threading.Thread(target=lambda: ctypes.windll.user32.MessageBoxW(0, text, "Telegram для лид-центра", 0x30 | 0x40000), daemon=True).start()
    except Exception:
        pass


def время_конфига():
    try:
        return os.path.getmtime(CONFIG)
    except OSError:
        return 0


async def ждать_конфиг(стоп=lambda: False, шаг=10):
    # ждём, пока config.json поменяется («Вставить ключ программы.bat», новый вход) — Telegram при этом не трогаем
    было = время_конфига()
    while время_конфига() == было and not стоп():
        await asyncio.sleep(шаг)


def автозапуск_включён():
    return os.path.exists(STARTUP_VBS) if WIN else (sys.platform == "darwin" and os.path.exists(PLIST))


def фоновая_жива():
    # pid фоновой копии из agent.pid, если такой процесс есть и это наша программа (номер мог достаться другой программе)
    try:
        pid = int(open(PIDFILE).read().strip())
    except Exception:
        return 0
    if pid == os.getpid():
        return 0
    try:
        if WIN:
            out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/FO", "CSV", "/NH"], capture_output=True, text=True,
                                 errors="replace", timeout=15, creationflags=0x08000000).stdout
            return pid if "python" in out.lower() else 0
        os.kill(pid, 0)
        cmd = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, errors="replace", timeout=5).stdout
        return pid if "tg_agent" in cmd else 0
    except Exception:
        return 0


def хвост_журнала(n=5):
    try:
        with open(LOG, encoding="utf-8", errors="replace") as f:
            return [x.rstrip("\n") for x in f.readlines()[-n:]]
    except Exception:
        return []


def показать_журнал(n=5):
    строки = хвост_журнала(n)
    if строки:
        print("Последние строки журнала (%s):" % LOG)
        for x in строки:
            print("  " + x)


# ---------- вход ----------
def load_cfg():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


KEY_FILE = "Ключ программы Telegram.txt"
KEY_RE = re.compile(r"(?<![A-Za-z0-9_\-])[A-Za-z0-9_\-]{30,100}(?![A-Za-z0-9_\-])")


def key_dirs():
    # где обычно лежит файл с ключом: рядом с программой, «Загрузки», рабочий стол (в т.ч. OneDrive)
    home = os.path.expanduser("~")
    return [os.path.dirname(os.path.abspath(__file__)), os.path.join(home, "Downloads"), os.path.join(home, "Загрузки"),
            os.path.join(home, "Desktop"), os.path.join(home, "OneDrive", "Desktop"), os.path.join(home, "OneDrive", "Рабочий стол")]


def key_from_files():
    for d in key_dirs():
        p = os.path.join(d, KEY_FILE)
        try:
            with open(p, encoding="utf-8-sig") as f:
                found = KEY_RE.findall(f.read())
        except Exception:
            continue
        if len(found) == 1:
            return found[0], p
    return "", ""


def ask_token(cfg):
    # ключ вставляют один раз (и при замене): его выдаёт ведущий, в файлах программы его нет.
    # Скрытый ввод (getpass) в окне Windows не принимает вставку — поэтому сначала файл, иначе видимый ввод
    t, src = key_from_files()
    if t:
        print("\nКлюч программы взят из файла: " + src)
    else:
        print("\nКлюч программы для сервера команды (agent_token — от ведущего).")
        print("Проще всего: положите файл «" + KEY_FILE + "» в папку программы или в «Загрузки» и запустите снова.")
        print("Или вставьте ключ сюда (правая кнопка мыши или Ctrl+V) и нажмите Enter.")
        try:
            raw = ввод_строки("Ключ: ").replace("\x16", "")
        except (ConsoleInputUnavailable, KeyboardInterrupt):
            print("\nКлюч не введён. Положите файл «" + KEY_FILE + "» в папку программы и запустите снова.")
            sys.exit(1)
        found = KEY_RE.findall(raw)
        t = found[0] if len(found) == 1 else raw.strip().strip('"').strip()
    if not re.fullmatch(r"[A-Za-z0-9_\-]{20,100}", t):
        print("Это не похоже на ключ программы (латиница, цифры, - и _, от 20 знаков). Ничего не сохранено.")
        sys.exit(1)
    cfg["agent_token"] = t
    save_cfg(cfg)
    if src:
        # ключ теперь только в config.json этого компьютера: файл с ним убираем, чтобы его не унесли вместе с папкой
        try:
            os.remove(src)
            print("Ключ сохранён на этом компьютере, файл с ключом удалён.")
        except Exception:
            print("Ключ сохранён на этом компьютере. Удалите файл с ключом: " + src)
    else:
        print("Ключ сохранён на этом компьютере.")
    return cfg


def save_cfg(cfg):
    os.makedirs(HOME, exist_ok=True)
    tmp = CONFIG + ".tmp"
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    os.replace(tmp, CONFIG)
    os.chmod(CONFIG, 0o600)


# ---------- прокси (tg-ws-proxy и любой MTProto-прокси) ----------
def port_open(host, port):
    import socket
    try:
        socket.create_connection((host, port), 1).close()
        return True
    except Exception:
        return False


def parse_proxy(text):
    # «tg://proxy?server=127.0.0.1&port=1443&secret=dd…», «https://t.me/proxy?…» или просто секрет (тогда 127.0.0.1:1443)
    t = (text or "").strip()
    if not t:
        return None
    if "secret=" in t:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(t.replace("tg://proxy", "tg://x/proxy")).query)
        return {"host": (q.get("server") or ["127.0.0.1"])[0], "port": int((q.get("port") or ["1443"])[0]), "secret": (q.get("secret") or [""])[0]}
    if re.fullmatch(r"(dd|ee)?[0-9a-fA-F]{32}", t) or re.fullmatch(r"[A-Za-z0-9_\-+/=]{20,}", t):
        return {"host": "127.0.0.1", "port": 1443, "secret": t}
    return None


def tgws_proxy():
    # tg-ws-proxy (Flowseal) хранит порт и секрет в %APPDATA%\TgWsProxy\config.json. Переустановили / обновили его —
    # секрет новый, а у нас старый, и Telegram молча не отвечает (TimeoutError). Поэтому берём настройки прямо оттуда.
    # Ссылка tg-ws-proxy — «secret=dd<секрет>»: без «dd» соединение не то
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    for d in (os.path.join(base, "TgWsProxy"), os.path.join(os.path.expanduser("~"), "Library", "Application Support", "TgWsProxy"),
              os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config"), "TgWsProxy")):
        try:
            with open(os.path.join(d, "config.json"), encoding="utf-8") as f:
                c = json.load(f)
        except Exception:
            continue
        sec = str(c.get("secret") or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{32}", sec):
            continue
        host = str(c.get("host") or "127.0.0.1").strip()
        if host in ("", "0.0.0.0", "::"):
            host = "127.0.0.1"
        try:
            port = int(c.get("port") or 1443)
        except Exception:
            port = 1443
        return {"host": host, "port": port, "secret": "dd" + sec}
    return None


def fix_proxy(cfg):
    # перед каждым подключением: настройки tg-ws-proxy главнее сохранённых; голый секрет из 32 знаков — с «dd»
    t = tgws_proxy()
    p = cfg.get("proxy")
    if t and p != t:
        cfg["proxy"] = t
        save_cfg(cfg)
        log("Прокси: взял настройки tg-ws-proxy (%s:%s)" % (t["host"], t["port"]))
    elif p and p.get("secret") and re.fullmatch(r"[0-9a-fA-F]{32}", str(p["secret"])):
        cfg["proxy"] = dict(p, secret="dd" + str(p["secret"]).lower())
        save_cfg(cfg)
    return cfg


async def check_connection():
    # «Проверить связь с Telegram.bat»: где обрыв — прокси, сеть или Telegram. Секреты и ключи не печатаются
    import socket
    cfg = load_cfg()
    print("\n=== Проверка связи с Telegram ===")
    try:
        import telethon
        print("Telethon:", getattr(telethon, "__version__", "?"), "| Python:", sys.version.split()[0])
    except Exception as e:
        print("Telethon не установлен:", e)
        return
    p, t = cfg.get("proxy"), tgws_proxy()
    show = lambda x: "нет" if not x else "%s:%s (секрет %s…, %d знаков)" % (x.get("host"), x.get("port"), str(x.get("secret", ""))[:2], len(str(x.get("secret", ""))))
    print("Прокси в программе:", show(p))
    print("Настройки tg-ws-proxy на компьютере:", show(t) + ("" if not t else (" — совпадают с программой" if t == p else " — НЕ совпадают с программой")))
    for x in [y for y in (p, t) if y]:
        print("Порт прокси %s:%s открыт:" % (x["host"], x["port"]), "да" if port_open(x["host"], int(x["port"])) else "НЕТ (tg-ws-proxy не запущен?)")
    for host in ("149.154.167.51", "149.154.175.53"):
        try:
            socket.create_connection((host, 443), 5).close()
            print("Прямая связь с сервером Telegram %s:443: есть" % host)
        except Exception as e:
            print("Прямая связь с сервером Telegram %s:443: НЕТ (%s)" % (host, type(e).__name__))
    # фоновая программа и ключ для сервера команды: без них Telegram «работает», а заданий нет
    pid, авто = фоновая_жива(), автозапуск_включён()
    print("Автозапуск:", "включён" if авто else "выключен", "| Программа в фоне:", ("работает (процесс %d)" % pid) if pid else "НЕ запущена")
    global AGENT_TOKEN
    if not cfg.get("agent_token"):
        print("Ключ программы для сервера команды: НЕТ — запустите «Вставить ключ программы.bat»")
    else:
        AGENT_TOKEN = str(cfg["agent_token"]).strip()
        try:
            team("agent_ping")
            print("Сервер команды принимает ключ программы: да")
        except KeyRejected:
            print("Сервер команды принимает ключ программы: НЕТ — запустите «Вставить ключ программы.bat»")
        except Exception as e:
            print("Сервер команды: не ответил (%s)" % str(e)[:120])
    показать_журнал(5)
    if not cfg.get("session"):
        print("Входа в Telegram нет — запустите программу и войдите.")
        return
    variants = []
    if t:
        variants.append(("через tg-ws-proxy (его настройки)", {"proxy": t}))
    if p and p != t:
        variants.append(("через прокси из программы", {"proxy": p}))
    variants.append(("напрямую, без прокси", {}))
    for name, c in variants:
        client = TelegramClient(StringSession(cfg["session"]), int(cfg["api_id"]), cfg["api_hash"], receive_updates=False,
                                connection_retries=1, timeout=15, **client_kwargs(c))
        try:
            await asyncio.wait_for(client.connect(), 40)
            me = await asyncio.wait_for(client.get_me(), 20)
            print("Telegram %s: РАБОТАЕТ (вошли как %s)" % (name, (me.first_name or "").strip()))
            сменил = c.get("proxy") != p
            if сменил:
                cfg["proxy"] = c.get("proxy")
                save_cfg(cfg)
                print("  → программа теперь подключается так.")
            if авто and (сменил or not pid):
                await client.disconnect()
                autostart(True)                     # фоновая копия — заново, с этими настройками; .bat запускать не нужно
            elif сменил or not pid:
                print("  → запустите «Запустить Telegram для лид-центра.bat».")
            return
        except Exception as e:
            print("Telegram %s: не отвечает (%s)" % (name, type(e).__name__))
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
    print("\nНи один способ не сработал. Откройте Telegram на этом компьютере: если и он не грузится — нет связи с Telegram у компьютера "
          "(включите tg-ws-proxy или VPN, в tg-ws-proxy правой кнопкой по значку → перезапуск). Пришлите этот текст ведущему.")


def ask_proxy(cfg):
    t = tgws_proxy()
    if t:
        cfg["proxy"] = t
        print("\nПрокси для Telegram: настройки взяты из tg-ws-proxy (%s:%s)." % (t["host"], t["port"]))
        return cfg
    found = port_open("127.0.0.1", 1443)
    print("\nПрокси для Telegram (tg-ws-proxy). " + ("На этом компьютере tg-ws-proxy запущен (порт 1443)." if found else "tg-ws-proxy на порту 1443 не найден."))
    print("Секрет: в tg-ws-proxy правой кнопкой по значку в трее → «Настройки…» (или ссылка «Открыть в Telegram»).")
    print("Вставьте секрет или ссылку tg://proxy?… (Enter — без прокси):")
    p = parse_proxy(ввод_строки("> "))
    cfg["proxy"] = p
    print("Прокси: " + ("%s:%s" % (p["host"], p["port"]) if p else "не используется"))
    return cfg


def client_kwargs(cfg):
    p = cfg.get("proxy")
    kw = {"device_model": "Lead-centre (компьютер)", "app_version": "1.0"}
    if p and p.get("secret"):
        from telethon import connection as C
        kw["connection"] = C.ConnectionTcpMTProxyRandomizedIntermediate if str(p["secret"]).lower().startswith("dd") else C.ConnectionTcpMTProxyIntermediate
        kw["proxy"] = (p.get("host") or "127.0.0.1", int(p.get("port") or 1443), str(p["secret"]))
    return kw


def скрытый_ввод(подсказка):
    # пароль не показываем: на Windows — звёздочки на каждый знак (видно, что вставка правой кнопкой сработала), иначе getpass
    if not WIN:
        return getpass.getpass(подсказка)
    import msvcrt
    print(подсказка, end="", flush=True)
    знаки = []
    while True:
        c = msvcrt.getwch()
        if c in ("\r", "\n"):
            print()
            return "".join(знаки)
        if c == "\x03":
            raise KeyboardInterrupt
        if c == "\x08":
            if знаки:
                знаки.pop()
                print("\b \b", end="", flush=True)
            continue
        if c in ("\x00", "\xe0"):
            msvcrt.getwch()                     # стрелки и F-клавиши — два кода, пропускаем
            continue
        if c == "\x16" or ord(c) < 32:
            continue                            # Ctrl+V в этом окне не вставляет — только правой кнопкой
        знаки.append(c)
        print("*", end="", flush=True)


async def login():
    if not доступен_ручной_ввод():
        raise ConsoleInputUnavailable(
            "Для входа откройте «ЗАПУСК 2.0.8 — нажать сюда.bat» вручную. "
            "Фоновая программа не может запросить телефон и код.")
    print("\n=== Вход в Telegram для лид-центра (один раз) ===")
    # 2.0.7: api_id / api_hash, прокси и ключ программы — из прошлого входа, если есть (после «Забыть вход» они остаются):
    # спрашиваем только телефон и код
    prev = load_cfg()
    api_id = int(prev["api_id"]) if str(prev.get("api_id", "")).isdigit() else None
    api_hash = prev.get("api_hash") if re.fullmatch(r"[0-9a-fA-F]{32}", str(prev.get("api_hash", ""))) else None
    if api_id and api_hash:
        print("api_id и api_hash — из прошлого входа.")
    else:
        api_id = api_hash = None
        print("api_id и api_hash: https://my.telegram.org → API development tools\n")
    while not api_id:
        api_id = ввод_строки("api_id: ").strip()
        if api_id.isdigit():
            api_id = int(api_id)
            break
        api_id = None
        print("api_id — только цифры (my.telegram.org → API development tools → App api_id). Ещё раз:")
    while not api_hash:
        api_hash = ввод_строки("api_hash: ").strip()
        if re.fullmatch(r"[0-9a-fA-F]{32}", api_hash):
            break
        api_hash = None
        print("api_hash — 32 знака (цифры и буквы a–f), там же, App api_hash. Ещё раз:")
    if "proxy" in prev:
        pcfg = {"proxy": prev.get("proxy")}
        пр = prev.get("proxy") if isinstance(prev.get("proxy"), dict) else None
        print("Прокси — как раньше: " + (("%s:%s" % (пр.get("host"), пр.get("port"))) if пр else "без прокси")
              + " (поменять — «Настроить прокси.bat»).")
    else:
        pcfg = ask_proxy({}) if (WIN or port_open("127.0.0.1", 1443)) else {}
    phone = ввод_строки("Номер телефона аккаунта (+7…): ").strip()
    if (not re.fullmatch(r"\+?[0-9][0-9 ()\-]{5,24}", phone)
            or not 7 <= len(re.sub(r"\D", "", phone)) <= 15):
        print("Номер не введён или имеет неверный формат. Данные входа не изменены.")
        sys.exit(1)
    client = TelegramClient(StringSession(), api_id, api_hash, **client_kwargs(pcfg))
    try:
        try:
            await asyncio.wait_for(client.connect(), 30)
        except Exception as e:
            print("\nНе удалось подключиться к Telegram (%s)." % type(e).__name__)
            print("Если Telegram на этом компьютере открывается только через tg-ws-proxy — запустите tg-ws-proxy и укажите его секрет.")
            sys.exit(1)
        await client.send_code_request(phone)
        import telethon.errors as TE
        код_неверный = tuple(getattr(TE, n) for n in ("PhoneCodeInvalidError", "PhoneCodeEmptyError") if hasattr(TE, n)) or (ValueError,)
        код_устарел = tuple(getattr(TE, n) for n in ("PhoneCodeExpiredError",) if hasattr(TE, n)) or (ValueError,)
        пароль_неверный = tuple(getattr(TE, n) for n in ("PasswordHashInvalidError",) if hasattr(TE, n)) or (ValueError,)
        нужен_пароль = False
        for попытка in range(3):                # код с опечаткой — ещё две попытки, не новый запрос кода
            code = ввод_строки("Код из Telegram: ").strip()
            try:
                await client.sign_in(phone=phone, code=code)
                break
            except SessionPasswordNeededError:
                нужен_пароль = True
                break
            except код_устарел:
                if попытка < 2:
                    print("Код устарел — Telegram пришлёт новый.")
                    await client.send_code_request(phone)
                else:
                    print("Код устарел; попытки ввода в этом запуске закончились.")
            except код_неверный:
                print("Код неверный — проверьте и введите ещё раз.")
        else:
            print("\nТри неудачные попытки. Запустите программу снова — Telegram пришлёт новый код.")
            sys.exit(1)
        if нужен_пароль:
            for попытка in range(3):
                pw = скрытый_ввод("Облачный пароль Telegram (вместо букв — звёздочки; вставка — правой кнопкой мыши): ")
                try:
                    await client.sign_in(password=pw)
                    break
                except пароль_неверный:
                    print("Пароль неверный — ещё раз.")
            else:
                print("\nТри неудачные попытки пароля. Запустите программу снова.")
                sys.exit(1)
        if not await client.is_user_authorized():
            raise RuntimeError("Telegram не подтвердил вход. Сохранённые настройки не изменены.")
        me = await client.get_me()
        if me is None:
            raise RuntimeError("Telegram не подтвердил аккаунт. Сохранённые настройки не изменены.")
        session = client.session.save()
        if not session:
            raise RuntimeError("Telegram не вернул сохраняемую сессию. Настройки не изменены.")
        cfg = {**prev, "api_id": api_id, "api_hash": api_hash, "session": session, "proxy": pcfg.get("proxy")}
        # Подтверждённый вход сохраняем атомарно ДО закрытия соединения.
        # Сбой disconnect не должен заставлять заново получать код Telegram.
        save_cfg(cfg)
    finally:
        try:
            await client.disconnect()
        except Exception:
            log("Не удалось штатно закрыть соединение входа. Настройки не удаляю.")
    print("\nВошли как:", ((me.first_name or "") + " " + (me.last_name or "")).strip(), "— вход сохранён на этом компьютере.")
    if not cfg.get("agent_token"):
        cfg = ask_token(cfg)                    # до автозапуска: фоновой программе ключ спросить негде
    try:
        автозапуск = ввод_строки("Запускать программу автоматически при включении компьютера? (да/нет): ")
    except ConsoleInputUnavailable:
        print("Вход уже сохранён. Автозапуск не включён: ответ не получен.")
        автозапуск = "нет"
    if автозапуск.strip().lower() in ("да", "д", "yes", "y"):
        autostart(True)
        print("Готово: программа уже работает в фоне и будет запускаться сама. Это окно можно закрыть.")
        if WIN:
            try:
                ввод_строки("Нажмите Enter, чтобы закрыть окно…")
            except ConsoleInputUnavailable:
                pass
        sys.exit(0)
    return cfg


def _copy_self():
    os.makedirs(HOME, exist_ok=True)
    me = os.path.join(HOME, "tg_agent.py")
    if os.path.realpath(__file__) != os.path.realpath(me):
        with open(__file__, encoding="utf-8") as src, open(me, "w", encoding="utf-8") as dst:
            dst.write(src.read())
    return me


def stop_running():
    # остановить фоновую программу (если запущена)
    try:
        pid = int(open(PIDFILE).read().strip())
    except Exception:
        return False
    if pid == os.getpid():
        return False
    try:
        if WIN:
            subprocess.call(["taskkill", "/PID", str(pid), "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            os.kill(pid, 15)
    except Exception:
        pass
    try:
        os.remove(PIDFILE)
    except Exception:
        pass
    return True


def autostart(on):
    if WIN:
        if os.path.exists(STARTUP_VBS):
            os.remove(STARTUP_VBS)
        if not on:
            stop_running()
            print("Автозапуск выключен, фоновая программа остановлена.")
            return
        me = _copy_self()
        exe = win_python()
        os.makedirs(os.path.dirname(STARTUP_VBS), exist_ok=True)
        with open(STARTUP_VBS, "w", encoding="utf-16") as f:     # VBScript понимает UTF-16 — русские пути не ломаются
            # 0 = окно скрыто: python.exe работает в фоне без чёрного окна
            f.write('CreateObject("WScript.Shell").Run """%s"" ""%s""", 0, False\r\n' % (exe, me))
        stop_running()
        subprocess.Popen([exe, me], creationflags=0x08000000 | 0x00000200, close_fds=True,      # без окна, отдельно от этого окна
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=HOME)
        print("Автозапуск включён: программа работает в фоне и сама запустится при входе в Windows.")
        print("Журнал работы:", LOG)
        return
    if sys.platform != "darwin":
        print("Автозапуск настраивается на Windows и Mac. Здесь запускайте программу вручную.")
        return
    if os.path.exists(PLIST):
        subprocess.call(["launchctl", "unload", PLIST], stderr=subprocess.DEVNULL)
        os.remove(PLIST)
    if not on:
        print("Автозапуск выключен.")
        return
    me = _copy_self()
    os.makedirs(os.path.dirname(PLIST), exist_ok=True)
    with open(PLIST, "w", encoding="utf-8") as f:
        f.write(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>ru.leadcentre.tgagent</string>
  <key>ProgramArguments</key><array><string>{venv_python()}</string><string>{me}</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>{LOG}</string>
  <key>StandardErrorPath</key><string>{LOG}</string>
</dict></plist>
""")
    subprocess.call(["launchctl", "load", PLIST])
    print("Автозапуск включён. Журнал работы:", LOG)


# ---------- задания ----------
def peer_of(e):
    from telethon.utils import get_input_peer
    return get_input_peer(e)


async def load_groups(client):
    groups = {}
    async for d in client.iter_dialogs(limit=400):
        if d.is_group:
            e = d.entity
            # старая группа, которую Telegram обновил до супергруппы (или из которой вышли), — писать туда нельзя
            if getattr(e, "deactivated", False) or getattr(e, "migrated_to", None) or getattr(e, "left", False) or type(e).__name__.endswith("Forbidden"):
                continue
            groups[str(d.id)] = {"title": d.title or "", "peer": peer_of(e), "forum": bool(getattr(e, "forum", False))}
    return groups


SCAN_PAT = {
    "approval": re.compile(r"соглас", re.I),
    "request": re.compile(r"заявк\w*\s*(№|#|n)?\s*\d{5,9}|№\s*\d{6,9}", re.I),
    "avito": re.compile(r"авито|avito", re.I),
    "review": re.compile(r"https?://(clck\.ru|clck\.su|clc\.li|golnk\.ru|www\.avito\.ru/brands)/\S+", re.I),
}
LINK_RX_ANY = re.compile(r"https?://(?:clck\.ru|clck\.su|clc\.li|golnk\.ru|www\.avito\.ru/brands)/[A-Za-z0-9_\-]+")
PHONE_RX = re.compile(r"(?<!\d)(\+?7|8)?[\s(\-]*\d{3}[\s)\-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)")


def mask(t):
    t = PHONE_RX.sub(" <тел>", t)
    t = LINK_RX_ANY.sub("<ссылка>", t)
    t = re.sub(r"(?i)(?<![а-яёa-z])(ул\.?|улица|пр-кт|проспект|пер\.?|переулок|ш\.|шоссе|мкр|д\.|дом|кв\.?|квартира|подъезд|этаж)\s*[^\s,;]+(\s+[^\s,;]+)?", r"\1 <…>", t)
    t = re.sub(r"(?i)(клиент\w*|имя|мастер\w*|зовут|фио)[:\s]+[А-ЯЁA-Z][а-яёa-z]+(\s+[А-ЯЁA-Z][а-яёa-z]+)?", r"\1 <имя>", t)
    t = re.sub(r"\d{2,}", lambda m: "#" * min(len(m.group(0)), 6), t)
    return re.sub(r"\s+", " ", t).strip()[:220]


# слова, которые можно не скрывать: города из названий групп и рабочие слова
WORK_WORDS = set("""заявка заявки заявку клиент клиента клиентка мастер мастера мс филиал филиала соглас согласование согласовано
адрес дата время сумма статус исполнитель назначен очереди красная партнер партнёр парт база мнч кп бт авито телевизор тв
холодильник стиральная посудомоечная компьютер ноутбук ремонт установка выезд диагностика бесплатно бесплатный цена от до
сегодня завтра понедельник вторник среда четверг пятница суббота воскресенье утро вечер обед после можно нельзя нет да ок
спасибо доброе добрый день вечер привет здравствуйте пожалуйста срочно важно внимание новый открылся закрыт создали создана
""".split())


MAP_RX = re.compile(r"https?://(?:www\.)?yandex\.(?:ru|com)/maps/\S*(?:um=constructor|constructor%3A|constructor:)\S*", re.I)
SHORT_MAP_RX = re.compile(r"https?://(?:www\.)?yandex\.(?:ru|com)/maps/-/[A-Za-z0-9_~\-]+", re.I)
_short_cache = {}


def _resolve_map(url):
    # короткая ссылка Яндекс Карт: оставляем, только если она ведёт на карту из конструктора (границы филиала)
    if url in _short_cache:
        return _short_cache[url]
    res = ""
    try:
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        op = urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=SSL))
        try:
            op.open(urllib.request.Request(url, method="GET", headers={"User-Agent": "Mozilla/5.0"}), timeout=8)
        except urllib.error.HTTPError as e:
            loc = e.headers.get("Location", "")
            if "constructor" in urllib.parse.unquote(loc):
                res = loc
    except Exception:
        pass
    _short_cache[url] = res
    return res


def keep_maps(t):
    # ссылки на карты границ филиалов — не данные клиента, их не скрываем (прячем под метку и возвращаем после маски)
    # от ссылки остаётся только номер карты: дом, координаты и точка клиента вырезаются
    keep = []
    def only_map(u):
        k = re.search(r"constructor(?:%3A|:)([A-Za-z0-9_\-]{10,})", urllib.parse.unquote(u) if "%" in u else u) or re.search(r"constructor(?:%3A|:)([A-Za-z0-9_\-]{10,})", u)
        if not k:
            return "<ссылка yandex.ru>"
        keep.append("https://yandex.ru/maps/?um=constructor:" + k.group(1))
        return " MAPKEEP%d " % (len(keep) - 1)
    t = MAP_RX.sub(lambda m: only_map(m.group(0)), t)
    t = SHORT_MAP_RX.sub(lambda m: only_map(_resolve_map(m.group(0))) if _resolve_map(m.group(0)) else m.group(0), t)
    return t, keep


def mask2(t, allow):
    t, keep = keep_maps(t)
    t = PHONE_RX.sub(" <тел>", t)
    t = re.sub(r"https?://([^/\s]+)\S*", r"<ссылка \1>", t)
    t = re.sub(r"\S+@\S+\.\w+", "<почта>", t)
    t = re.sub(r"(?i)(?<![а-яёa-z])(ул\.?|улица|пр-кт|проспект|пр\.|пер\.?|переулок|ш\.|шоссе|мкр\.?|микрорайон|д\.|дом|кв\.?|квартира|подъезд|под\.|этаж|корп\.?|корпус|стр\.?|снт|тер\.?)\s*[^\s,;]+(\s+[^\s,;]+)?", r"\1 <…>", t)
    # слова с заглавной буквы (имена, фамилии, улицы), кроме городов и рабочих слов
    def name(m):
        w = m.group(0)
        return w if w.lower() in allow or w.lower() in WORK_WORDS or w.isupper() and len(w) <= 4 else "<И>"
    t = re.sub(r"(?<=[^\s.!?…\n]\s)[А-ЯЁ][а-яё]{2,}|(?<=[,:;(]\s)[А-ЯЁ][а-яё]{2,}", name, t)
    t = re.sub(r"(?<!MAPKEEP)\d{2,}", lambda m: "#" * min(len(m.group(0)), 6), t)
    t = re.sub(r"MAPKEEP(\d+)", lambda m: keep[int(m.group(1))] if int(m.group(1)) < len(keep) else "", t)
    return re.sub(r"[ \t]+", " ", t).strip()


def template(t, allow):
    # первая строка сообщения (обезличенная, без цифр) — чтобы увидеть повторяющиеся шаблоны
    line = mask2(t.strip().split("\n")[0], allow)[:60]
    line = re.sub(r"\d+", "#", line)
    return re.sub(r"\s+", " ", line).strip()


async def scan(client, groups, start, n, depth):
    ids = sorted(groups, key=lambda k: groups[k]["title"])
    allow = {w.lower() for g in groups.values() for w in re.findall(r"[А-ЯЁа-яё\-]{3,}", g["title"])}
    out = []
    for cid in ids[start:start + n]:
        st = {"id": cid, "title": groups[cid]["title"], "msgs": 0, "mine": 0, "approval": 0, "request": 0, "avito": 0, "review": 0,
              "samples": {}, "links": {}, "lists": [], "templates": {}, "senders": {}, "replies": 0, "bots": 0}
        if n == 1:
            st["sample"] = []                                     # одна группа — показываем и сами сообщения (обезличенно)
        async for m in client.iter_messages(groups[cid]["peer"], limit=depth):
            t = m.message or ""
            if not t.strip():
                continue
            st["msgs"] += 1
            tp = template(t, allow)
            st["templates"][tp] = st["templates"].get(tp, 0) + 1
            sid = "я" if m.out else "у" + str(abs(hash(getattr(m, "sender_id", 0))) % 997)
            st["senders"][sid] = st["senders"].get(sid, 0) + 1
            st["replies"] += 1 if getattr(m, "reply_to", None) else 0
            st["bots"] += 1 if getattr(m, "via_bot_id", None) or (getattr(m, "sender", None) is not None and getattr(m.sender, "bot", False)) else 0
            if n == 1 and len(st["sample"]) < 40:
                st["sample"].append(("[я] " if m.out else "[" + sid + "] ") + ("↪ " if getattr(m, "reply_to", None) else "") + mask2(t, allow)[:400])
            st["mine"] += 1 if m.out else 0
            for k, rx in SCAN_PAT.items():
                if rx.search(t):
                    st[k] += 1
                    if k != "review" and len(st["samples"].setdefault(k, [])) < 2:
                        st["samples"][k].append(("[моё] " if m.out else "") + mask(t))
            links = LINK_RX_ANY.findall(t)
            for ln in links:
                st["links"][ln] = st["links"].get(ln, 0) + 1
            if len(links) >= 5 and len(st["lists"]) < 2:          # похоже на список источников — он без данных клиентов
                st["lists"].append(PHONE_RX.sub(" <тел>", t[:6000]))
        st["links"] = dict(sorted(st["links"].items(), key=lambda x: -x[1])[:40])
        st["templates"] = dict(sorted(st["templates"].items(), key=lambda x: -x[1])[:15])
        st["senders"] = len(st["senders"])
        out.append(st)
    return {"total": len(ids), "from": start, "groups": out}


async def search_links(client, groups):
    # где в аккаунте встречаются ссылки для отзывов: по каким чатам, сколько, и сами списки (без телефонов)
    allow = {w.lower() for g in groups.values() for w in re.findall(r"[А-ЯЁа-яё\-]{3,}", g["title"])}
    by_chat, lists, seen = {}, [], set()
    me = (await client.get_me()).id
    for q in ("clck.ru", "clc.li", "avito.ru/brands", "golnk.ru", "clck.su"):
        async for m in client.iter_messages(None, search=q, limit=300):
            if (m.chat_id, m.id) in seen:
                continue
            seen.add((m.chat_id, m.id))
            t = m.message or ""
            links = LINK_RX_ANY.findall(t)
            if not links:
                continue
            g = groups.get(str(m.chat_id))
            title = g["title"] if g else ("Избранное" if m.chat_id == me else "личный чат или канал")
            st = by_chat.setdefault(title, {"msgs": 0, "links": {}, "mine": 0, "last": 0, "pinned_like": 0, "samples": []})
            st["msgs"] += 1
            st["mine"] += 1 if m.out else 0
            st["last"] = max(st["last"], int(m.date.timestamp()))
            for ln in links:
                st["links"][ln] = st["links"].get(ln, 0) + 1
            if len(links) >= 5:
                st["pinned_like"] += 1
                if len(lists) < 8:
                    lists.append({"chat": title, "at": int(m.date.timestamp()), "text": PHONE_RX.sub(" <тел>", t[:6000])})
            elif len(st["samples"]) < 3:
                st["samples"].append(mask2(t, allow)[:300])
    for st in by_chat.values():
        st["links_total"] = len(st["links"])
        st["links"] = dict(sorted(st["links"].items(), key=lambda x: -x[1])[:15])
    return {"chats": dict(sorted(by_chat.items(), key=lambda x: -x[1]["msgs"])), "lists": lists}


async def search_text(client, groups, q, limit):
    # поиск слова по всем группам аккаунта; тексты — обезличенные (личные чаты не берём)
    allow = {w.lower() for g in groups.values() for w in re.findall(r"[А-ЯЁа-яё\-]{3,}", g["title"])}
    out = []
    async for m in client.iter_messages(None, search=q, limit=limit * 2):
        g = groups.get(str(m.chat_id))
        if not g or not (m.message or "").strip():
            continue
        out.append({"chat": g["title"], "at": int(m.date.timestamp()), "mine": bool(m.out),
                    "text": mask2(m.message, allow)[:1500]})
        if len(out) >= limit:
            break
    return {"q": q, "found": len(out), "messages": out}


async def replies(client, peer, mid):
    out = []
    async for m in client.iter_messages(peer, min_id=mid, limit=200):
        rt = getattr(m, "reply_to", None)
        if m.out or not rt or getattr(rt, "reply_to_msg_id", None) != mid or not (m.message or "").strip():
            continue
        who = await m.get_sender()
        name = ((getattr(who, "first_name", "") or "") + " " + (getattr(who, "last_name", "") or "")).strip() or getattr(who, "title", "") or ""
        out.append({"id": m.id, "from": name[:40], "text": m.message[:1000], "at": int(m.date.timestamp())})
    return sorted(out, key=lambda x: x["at"])


async def recent(client, peer, n, since):
    # последние сообщения чата города — расширение проверяет, нет ли неотвеченной просьбы филиала,
    # чтобы не написать своё поверх неё («защита от перекрытия»)
    out = []
    async for m in client.iter_messages(peer, limit=n):
        at = int(m.date.timestamp())
        if since and at < since:
            break
        who = getattr(m, "sender", None)
        if who is None and not m.out:
            try:
                who = await m.get_sender()
            except Exception:
                who = None
        name = ((getattr(who, "first_name", "") or "") + " " + (getattr(who, "last_name", "") or "")).strip() or getattr(who, "title", "") or ""
        rt = getattr(m, "reply_to", None)
        out.append({"id": m.id, "at": at, "out": bool(m.out), "from": name[:40], "bot": bool(getattr(who, "bot", False)),
                    "reply_to": int(getattr(rt, "reply_to_msg_id", 0) or 0), "mentioned": bool(getattr(m, "mentioned", False)),
                    "text": (m.message or "")[:400]})
    # ответ на НАШЕ сообщение, которое старше окна: помечаем reply_out, чтобы не принять ответ нам за просьбу
    ids = {x["id"] for x in out}
    mine = {x["id"]: x["out"] for x in out}
    need = sorted({x["reply_to"] for x in out if x["reply_to"] and x["reply_to"] not in ids})[:30]
    if need:
        try:
            for t in await client.get_messages(peer, ids=need):
                if t is not None:
                    mine[t.id] = bool(t.out)
        except Exception:
            pass
    for x in out:
        x["reply_out"] = bool(x["reply_to"] and mine.get(x["reply_to"]))
    return sorted(out, key=lambda x: x["at"])


# 2.1.3: защита от перекрытия — та же, что в расширении (ext/tg.js, LC_TG.просьбыФилиала), чтобы проверить и отправить ОДНИМ заданием.
# Правила менять в обоих местах: tests/guard_parity_test.js сверяет их на общих случаях
ПРОСТО_ОК = re.compile(r"^(ок|окей|ok|хорошо|спасибо|спс|принято|принял|понял|поняла|да|нет|\+|👍|ага|ясно|добро|отлично)[\s.!)]*$", re.I)
ОТЧЁТ = re.compile(r"^(\d{6,8}\s*[-–—:,]?\s*)?([а-яё]+\s+){0,2}?(закрыл|закрыла|закрыта|закрыто|выполн|сделал|сделано|сделана|принял|принята|взял|взяли|еду|едет|в пути|на месте|приехал|отработ|оплач|отказ клиента)", re.I)
ПРОСЬБА = re.compile(r"\?|перенос|перенес|перенести|отмен|позвоните|перезвоните|наберите|уточните|скиньте|напишите|предупредите|сообщите|свяжитесь|подтвердите|передайте|согласуйте|срочно|не отвечает|не бер[её]т|недозвон|не открывает|нет дома", re.I)
ПРОСЬБА_В_ОТВЕТЕ = re.compile(r"\?|позвоните|перезвоните|наберите|уточните|перенесите|отмените|скиньте|напишите|предупредите|свяжитесь|подтвердите|сообщите|передайте", re.I)
НАШИ_ЛЮДИ = re.compile(r"чатер|(^|[^а-яё])кц([^а-яё]|$)|лид-?центр|колл-?центр|call", re.I)
ФОРМАТ_КЦ = re.compile(r"перенос\s+с\s+[\"«]?\d{1,2}\.\d{1,2}\.\d{2,4}\s*/?\s*\d{1,2}:\d{2}[\"»]?\s+на\s+[\"«]?\d{1,2}\.\d{1,2}", re.I)
НОМЕР = re.compile(r"(?<!\d)\d{6,8}(?!\d)")


def просьбы_филиала(msgs, now=None, окно=1800):
    now = now or time.time()
    lst = sorted(msgs or [], key=lambda m: m.get("at", 0))
    наши = {m.get("id") for m in lst if m.get("out")}
    out = []
    for i, m in enumerate(lst):
        if m.get("out") or m.get("bot") or now - m.get("at", 0) > окно:
            continue
        if НАШИ_ЛЮДИ.search(str(m.get("from") or "")):
            continue
        t = str(m.get("text") or "").strip()
        if ФОРМАТ_КЦ.search(t) or not t or ПРОСТО_ОК.search(t) or ОТЧЁТ.search(t):
            continue
        номера = НОМЕР.findall(t)
        if not (m.get("mentioned") or ПРОСЬБА.search(t)):
            continue
        if (m.get("reply_to") in наши or m.get("reply_out")) and not ПРОСЬБА_В_ОТВЕТЕ.search(t):
            continue
        после = [x for x in lst[i + 1:] if x.get("out")]
        if any(x.get("reply_to") == m.get("id") or any(n in str(x.get("text") or "") for n in номера) for x in после):
            continue
        out.append(m)
    return out


# 2.0.4: сколько ждать Telegram на задание. Сервер ждёт ответа 25 с (с фото — 40): дольше ждать незачем, а зависшая связь
# с Telegram должна быть видна сразу. Сводки и поиск — долгие сами по себе
СРОК_ЗАДАНИЯ = {"scan": 100, "search": 100}
СРОК_ПРОВЕРКИ = 15          # «Telegram жив?» (get_me)
ТИШИНА_ПРОВЕРКИ = 120       # без удачных заданий дольше — проверяем связь сами


def срок_задания(job):
    k, a = job.get("kind"), job.get("args") or {}
    return СРОК_ЗАДАНИЯ.get(k) or (60 if a.get("photos") else 30)


class Agent:
    def __init__(self, client):
        self.client, self.groups, self.groups_at = client, {}, 0
        self.tasks, self.heavy = set(), asyncio.Semaphore(1)       # сводки — по одной, остальное сразу
        # 2.0.4: сторож связи с Telegram. Бывало: программа «на связи» (сервер её видит), а Telegram внутри завис — задания
        # не выполнялись до перезапуска программы вручную (11.10: перестали уходить сообщения в «Авито-Чаты»).
        # Задание не дождалось Telegram — проверяем связь; не отвечает — переподключаемся сами
        self.зависло, self.ок_at = 0, time.time()

    async def handle(self, job):
        try:
            if job.get("kind") == "scan":
                async with self.heavy:
                    r = await asyncio.wait_for(self.do(job), срок_задания(job))
            else:
                r = await asyncio.wait_for(self.do(job), срок_задания(job))
            res = {"id": job["id"], "result": r}
            self.зависло, self.ок_at = 0, time.time()
        except asyncio.TimeoutError:
            self.зависло += 1
            log("Telegram не ответил за %d с (задание %s) — проверю связь" % (срок_задания(job), job.get("kind")))
            res = {"id": job["id"], "error": "Telegram на компьютере не ответил вовремя — программа проверяет связь и переподключится сама"}
        except Exception as e:
            log("Ошибка задания", job.get("kind"), "—", type(e).__name__, str(e)[:150])
            res = {"id": job["id"], "error": (str(e) if isinstance(e, RuntimeError) else type(e).__name__ + ": " + str(e))[:300]}
        try:
            await asyncio.to_thread(team, "agent_done", res)
        except Exception as e:
            log("Не удалось вернуть результат:", type(e).__name__)

    async def жив(self):
        try:
            await asyncio.wait_for(self.client.get_me(), СРОК_ПРОВЕРКИ)
            self.зависло, self.ок_at = 0, time.time()
            return True
        except asyncio.TimeoutError:
            return False
        except (ConnectionError, OSError):
            return False

    async def сторож(self):
        # задание не дождалось Telegram или давно не было удачных — «Telegram жив?»; нет — наверх: main() отметит
        # «Telegram не подключён» (оператор сразу видит причину, а не «не ответил вовремя») и переподключится
        if not self.зависло and time.time() - self.ок_at < ТИШИНА_ПРОВЕРКИ:
            return
        if await self.жив():
            return
        log("Telegram на компьютере не отвечает — переподключаюсь")
        raise asyncio.TimeoutError("Telegram не отвечает")

    async def refresh(self):
        self.groups = await load_groups(self.client)
        self.groups_at = time.time()
        await asyncio.to_thread(team, "agent_chats", {"chats": {k: {"title": v["title"], "forum": v.get("forum", False)} for k, v in self.groups.items()}})
        log("Групп в аккаунте:", len(self.groups))

    def group(self, cid):
        g = self.groups.get(str(cid))
        if not g:
            raise RuntimeError("группа не найдена среди групп аккаунта")
        return g

    async def do(self, job):
        kind, a = job.get("kind"), job.get("args") or {}
        if kind == "send":
            g = self.group(a["chat"])
            photos = a.get("photos") or []
            if photos:
                import base64 as b64, io
                files = []
                for i, ph in enumerate(photos[:4]):
                    f = io.BytesIO(b64.b64decode(ph["b64"]))
                    f.name = "photo%d.jpg" % (i + 1)
                    files.append(f)
                # подпись в Telegram — до 1024 знаков; длиннее — фото отдельно, текст отдельным сообщением
                text = str(a["text"])[:3500]
                if len(text) <= 1000:
                    ms = await self.client.send_file(g["peer"], files, caption=text, reply_to=int(a.get("reply_to") or 0) or None)
                    m = ms[0] if isinstance(ms, list) else ms
                else:
                    m = await self.client.send_message(g["peer"], text, reply_to=int(a.get("reply_to") or 0) or None, link_preview=False)
                    await self.client.send_file(g["peer"], files, reply_to=m.id)
                log("Отправлено в «%s» (фото: %d)" % (g["title"], len(files)))
                return m.id
            m = await self.client.send_message(g["peer"], str(a["text"])[:3500], reply_to=int(a.get("reply_to") or 0) or None, link_preview=False)
            log("Отправлено в «%s»" % g["title"])
            return m.id
        if kind == "send_guarded":
            # 2.1.3: проверить чат города и сразу отправить — одно задание вместо двух. Ждёт ответа просьба филиала — не отправляем,
            # отдаём её (расширение покажет окно «ответьте филиалу / всё равно отправить»)
            g = self.group(a["chat"])
            msgs = await recent(self.client, g["peer"], min(int(a.get("n", 30) or 30), 50), int(a.get("since", 0) or 0))
            ждёт = просьбы_филиала(msgs)
            if ждёт:
                log("Не отправил в «%s»: ждёт ответа просьба филиала" % g["title"])
                return {"guard": ждёт[-3:]}
            return {"message_id": await self.do({"kind": "send", "args": {k: v for k, v in a.items() if k not in ("since", "n")}})}
        if kind == "send_me":
            # уведомление мозга владельцу (лимит расходов на ИИ) — в «Избранное» этого аккаунта
            m = await self.client.send_message("me", str(a.get("text", ""))[:1000], link_preview=False)
            log("Уведомление мозга — в «Избранное»")
            return m.id
        if kind == "replies":
            return await replies(self.client, self.group(a["chat"])["peer"], int(a["msg"]))
        if kind == "recent":
            return await recent(self.client, self.group(a["chat"])["peer"], min(int(a.get("n", 30)), 50), int(a.get("since", 0) or 0))
        if kind == "chats":
            await self.refresh()
            return len(self.groups)
        if kind == "scan" and int(a.get("from", 0)) < 0:
            log("Поиск ссылок на отзывы по всему аккаунту")
            return await search_links(self.client, self.groups)
        if kind == "scan":
            log("Сводка по чатам: с %s, по %s" % (a.get("from", 0), a.get("n", 8)))
            return await scan(self.client, self.groups, int(a.get("from", 0)), min(int(a.get("n", 8)), 12), min(int(a.get("depth", 200)), 400))
        if kind == "search":
            log("Поиск по группам: «%s»" % str(a.get("q", ""))[:40])
            return await search_text(self.client, self.groups, str(a.get("q", ""))[:60], min(int(a.get("limit", 60)), 150))
        if kind == "topics":
            # разделы (темы) группы-форума: «Авито-Чаты» → «Созданные с Авито», «Вопросы по Авито»…
            # в раздел пишут ответом на его номер (reply_to = id раздела)
            g = self.group(a["chat"])
            if not g.get("forum"):
                return []
            try:
                from telethon.tl.functions.messages import GetForumTopicsRequest
            except ImportError:
                from telethon.tl.functions.channels import GetForumTopicsRequest
            res = await self.client(GetForumTopicsRequest(g["peer"], offset_date=None, offset_id=0, offset_topic=0, limit=100))
            return [{"id": t.id, "title": t.title} for t in res.topics if getattr(t, "title", None)]
        if kind == "ping":
            t = time.time()
            await self.client.get_me()
            return {"groups": len(self.groups), "telegram_ms": int((time.time() - t) * 1000)}
        raise RuntimeError("неизвестное задание: " + str(kind))

    async def run(self):
        # сервер команды не ответил — ждём его, НЕ переподключая Telegram: раньше каждая ошибка сервера рвала связь с Telegram
        # и программа входила в Telegram заново каждые 20 с (так Telegram / прокси могут временно перестать пускать)
        while True:
            try:
                await self.refresh()
                break
            except KeyRejected:
                raise                                   # ключ не принят — ждать сервер бессмысленно (main ждёт новый ключ)
            except Exception as e:
                log("Сервер команды пока не отвечает:", type(e).__name__, str(e)[:120], "— жду 30 с, Telegram не переподключаю")
                await asyncio.sleep(30)
        idle_since, errors = time.time(), 0
        log("На связи. Окно не закрывайте (или включите автозапуск: «Включить автозапуск.bat» / tg_agent.py --autostart).")
        while True:
            try:
                jobs = json.loads(await asyncio.to_thread(poll)).get("jobs", [])
                errors = 0
            except KeyRejected:
                log("Нет связи с сервером команды: ключ не принят")
                raise
            except Exception as e:
                errors += 1
                if errors in (1, 5) or errors % 30 == 0:
                    log("Нет связи с сервером команды:", type(e).__name__, str(e)[:120])
                await asyncio.sleep(min(30, 3 * errors))
                continue
            for job in jobs:
                idle_since = time.time()
                # каждое задание — отдельно: долгая сводка не задерживает отправку согласования
                t = asyncio.create_task(self.handle(job))
                self.tasks.add(t)
                t.add_done_callback(self.tasks.discard)
            await self.сторож()
            if time.time() - self.groups_at > 600:
                try:
                    await self.refresh()
                except Exception as e:
                    log("Не удалось обновить группы:", type(e).__name__)
            # каждые 3 с, если полчаса тихо — реже (сервер считает программу на связи 45 с)
            # раз в 1,5 с всегда: сервер отвечает на пустую очередь почти бесплатно (без списка), задание подхватывается сразу
            await asyncio.sleep(1.0)                    # 2.1.3: было 1,5 с — задание подхватывается быстрее


def версия_файл():
    return os.path.join(HOME, "version.txt")


def _прочитать(путь):
    try:
        with open(путь, encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def копии_программы():
    # все tg_agent.py этой программы на компьютере: копия автозапуска + папки на рабочем столе, в «Загрузках», «Документах», OneDrive.
    # Старую копию запускали «не из той» папки (вложенная распаковка, старый ярлык) — и работала старая версия
    дом = os.path.expanduser("~")
    корни = [HOME] + [os.path.join(дом, x) for x in ("Desktop", "Downloads", "Documents", "Рабочий стол", "Загрузки", "Документы")]
    od = os.path.join(дом, "OneDrive")
    if os.path.isdir(od):
        корни += [od] + [os.path.join(od, x) for x in ("Desktop", "Documents", "Рабочий стол", "Документы")]
    я, найдено = os.path.realpath(__file__), []
    for корень in корни:
        if not os.path.isdir(корень):
            continue
        глубина0 = корень.rstrip(os.sep).count(os.sep)
        for папка, подпапки, файлы in os.walk(корень):
            if папка.count(os.sep) - глубина0 >= 4:
                подпапки[:] = []
            подпапки[:] = [x for x in подпапки if not x.startswith(".") or os.path.join(папка, x) == HOME]
            if "tg_agent.py" in файлы:
                путь = os.path.realpath(os.path.join(папка, "tg_agent.py"))
                if путь != я and путь not in найдено:
                    найдено.append(путь)
    return найдено


def обновить_копии():
    # чужие (старые) копии этой программы — заменить этой версией; файл чужой программы с тем же именем не трогаем
    with open(__file__, encoding="utf-8") as f:
        моя = f.read()
    обновлено = []
    for путь in копии_программы():
        try:
            with open(путь, encoding="utf-8", errors="replace") as f:
                было = f.read()
            if было == моя or ("lead-centre" not in было and "лид-центр" not in было.lower()):
                continue
            with open(путь, "w", encoding="utf-8") as f:
                f.write(моя)
            обновлено.append(путь)
        except Exception:
            pass
    return обновлено


def чужие_копии(процессы, мой):
    """процессы — [(pid, ppid, командная строка)] с tg_agent.py; что остановить. 14.10: на Windows программа запускается
    цепочкой py.exe → python → python из своей папки (venv, у него ещё и свой запускатель) — у ВСЕХ в командной строке
    tg_agent.py. Раньше останавливалось всё, кроме себя, — и свои же родители: окно «Запустить…» сразу писало
    «Press any key», а нажатие закрывало окно вместе с программой (вход в Telegram был невозможен). Своя цепочка — не копии"""
    родитель = {pid: ppid for pid, ppid, _ in процессы}
    свои, p = {мой}, родитель.get(мой)
    while p and p not in свои:
        свои.add(p)
        p = родитель.get(p)
    return [pid for pid, _, cmd in процессы if pid not in свои and "tg_agent.py" in str(cmd).lower()]


def остановить_все_копии():
    # на Windows — все процессы с tg_agent.py, кроме этого и его цепочки запуска (не только из agent.pid: старая копия
    # могла его перезаписать)
    if not WIN:
        return stop_running()
    кмд = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*tg_agent.py*' } | "
           "ForEach-Object { '{0}|{1}|{2}' -f $_.ProcessId, $_.ParentProcessId, $_.CommandLine }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", кмд], capture_output=True, text=True,
                             errors="replace", timeout=30, creationflags=0x08000000).stdout
        процессы = []
        for строка in out.splitlines():
            части = строка.strip().split("|", 2)
            if len(части) == 3 and части[0].isdigit() and части[1].isdigit():
                процессы.append((int(части[0]), int(части[1]), части[2]))
        чужие = чужие_копии(процессы, os.getpid())
        for pid in чужие:
            subprocess.call(["taskkill", "/PID", str(pid), "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=0x08000000)
        return bool(чужие) or stop_running()
    except Exception:
        return stop_running()


async def main():
    os.makedirs(HOME, exist_ok=True)
    # автозапуск Windows/Mac запускает КОПИЮ программы из ~/.lead-centre-tg — после замены файлов в папке она оставалась старой
    # и при входе в Windows снова поднимала старую версию (та гасила новую). Запуск из папки обновляет копию автозапуска
    print("Программа Telegram для лид-центра " + ВЕРСИЯ_ПРОГРАММЫ, flush=True)
    обновлена = False
    try:
        for путь in обновить_копии():
            обновлена = True
            log("Старая копия программы заменена этой версией:", путь)
    except Exception as e:
        log("Не смог обновить старые копии программы:", type(e).__name__)
    if обновлена:
        _copy_self()
    # запуск вручную (окно), а программа уже работает в фоне от автозапуска: не гасим её, а так и говорим.
    # Файлы обновили — фоновую копию перезапускаем уже новой
    if not без_консоли() and автозапуск_включён() and load_cfg().get("session") and load_cfg().get("agent_token"):
        if обновлена:
            print("Программа обновлена до версии " + ВЕРСИЯ_ПРОГРАММЫ + " — перезапускаю её в фоне.")
            autostart(True)
            return
        if фоновая_жива() and _прочитать(версия_файл()) == ВЕРСИЯ_ПРОГРАММЫ:
            print("Программа уже работает в фоне — всё в порядке. Это окно можно закрыть.")
            показать_журнал(5)
            return
    # на компьютере должна работать одна копия: две забирали одно задание и сообщение уходило дважды
    if остановить_все_копии():
        log("Прежняя копия программы остановлена — работает эта")
        time.sleep(1)
    log("Программа Telegram для лид-центра " + ВЕРСИЯ_ПРОГРАММЫ)
    try:
        with open(PIDFILE, "w") as f:
            f.write(str(os.getpid()))
        with open(версия_файл(), "w") as f:
            f.write(ВЕРСИЯ_ПРОГРАММЫ)
    except Exception:
        pass
    cfg = load_cfg()
    if not cfg.get("session"):
        cfg = await login()
    if not cfg.get("agent_token"):
        if not доступен_ручной_ввод():
            log("Нет ключа программы для сервера команды: запустите «Вставить ключ программы.bat» (tg_agent.py --token)")
            sys.exit(1)
        cfg = ask_token(cfg)
    global AGENT_TOKEN
    AGENT_TOKEN = str(cfg["agent_token"]).strip()
    said = None
    тик = None                                  # пульс tg_down, пока Telegram не подключается

    def нет_telegram(why):
        nonlocal тик
        СВЯЗЬ["state"], СВЯЗЬ["why"] = "tg_down", why
        if тик is None or тик.done():
            тик = asyncio.create_task(пульс())

    def есть_telegram():
        nonlocal тик
        СВЯЗЬ["state"], СВЯЗЬ["why"] = "ok", ""
        if тик is not None:
            тик.cancel()
            тик = None

    async def ключ_не_принят():
        # ключ отклонён (403): Telegram не переподключаем по кругу, а ждём новый ключ в config.json
        nonlocal cfg, said
        global AGENT_TOKEN
        есть_telegram()
        СВЯЗЬ["key_bad"] = False
        log("Сервер команды не принял ключ программы. " + КЛЮЧ_НЕ_ПРИНЯТ + " — программа подождёт новый ключ (Telegram не переподключаю)")
        if без_консоли():
            окно(КЛЮЧ_НЕ_ПРИНЯТ)
        # config.json поменялся (вставили ключ) — пробуем; раз в 30 мин — тоже (ключ могли принять на сервере)
        while True:
            с = time.time()
            await ждать_конфиг(lambda: time.time() - с > 1800)
            cfg = load_cfg()
            AGENT_TOKEN = str(cfg.get("agent_token") or "").strip()
            if not AGENT_TOKEN:
                continue
            try:
                await asyncio.to_thread(team, "agent_ping")
                break
            except KeyRejected:
                continue
            except RuntimeError:
                break                                   # старый сервер без agent_ping (ключ принял) или 502/холодный старт — не ждём 30 мин
            except Exception:
                break                                   # сервер не ответил — дальше как обычно (ждём его, Telegram не трогаем)
        СВЯЗЬ["sent"] = ""
        said = None
        log("Ключ программы принят — подключаюсь снова")

    while True:
        if СВЯЗЬ["key_bad"]:
            await ключ_не_принят()
        cfg = fix_proxy(cfg)
        pp = cfg.get("proxy")
        now_s = ("через прокси %s:%s" % (pp.get("host"), pp.get("port"))) if pp else "без прокси"
        if now_s != said:
            log("Подключаюсь к Telegram " + now_s + ("" if not pp else (" (настройки tg-ws-proxy)" if pp == tgws_proxy() else "")))
            said = now_s
        client = TelegramClient(StringSession(cfg["session"]), int(cfg["api_id"]), cfg["api_hash"],
                                receive_updates=False, **client_kwargs(cfg))
        try:
            await client.connect()
            if not await client.is_user_authorized():
                log("Вход в Telegram больше не действует: «Забыть вход» (tg_agent.py --logout), затем запустите программу и войдите заново")
                нет_telegram("auth")
                await client.disconnect()
                await ждать_конфиг(lambda: СВЯЗЬ["key_bad"])      # новый вход (или ключ) — тогда снова
                cfg = load_cfg()
                if not cfg.get("session"):
                    log("Входа в Telegram нет — запустите «Запустить Telegram для лид-центра.bat» и войдите")
                    sys.exit(1)
                continue
            me = await client.get_me()
            log("Telegram: вошли как", ((me.first_name or "") + " " + (me.last_name or "")).strip())
            есть_telegram()
            await Agent(client).run()
        except KeyRejected:
            СВЯЗЬ["key_bad"] = True                     # в начале круга: одна строка в журнал и ожидание нового ключа
        except (ConnectionError, OSError, asyncio.TimeoutError) as e:
            p = cfg.get("proxy")
            нет_telegram("proxy" if p else "net")
            if p and not port_open(p.get("host") or "127.0.0.1", int(p.get("port") or 1443)):
                log("Нет связи с Telegram: tg-ws-proxy не запущен (%s:%s). Запустите его — программа подключится сама." % (p.get("host"), p.get("port")))
            elif p:
                log("Нет связи с Telegram через tg-ws-proxy (%s:%s, %s). Повтор через 20 с. tg-ws-proxy запущен, но Telegram через него не отвечает: "
                    "проверьте интернет; в tg-ws-proxy правой кнопкой по значку → «Перезапустить прокси» (или закройте и откройте его снова)."
                    % (p.get("host"), p.get("port"), type(e).__name__))
            else:
                log("Нет связи с Telegram (%s). Повтор через 20 с. Если Telegram открывается только через tg-ws-proxy/VPN — включите его "
                    "(tg-ws-proxy программа найдёт сама) или «Настроить прокси.bat»." % type(e).__name__)
            await asyncio.sleep(20)
        except Exception as e:
            log("Сбой:", type(e).__name__, str(e)[:200], "— перезапуск через 20 с")
            await asyncio.sleep(20)
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass


def перезапустить_фон(иначе):
    # фоновая программа читает config.json при старте: после смены прокси / ключа её перезапускаем сами (если автозапуск включён)
    if автозапуск_включён():
        autostart(True)
    else:
        print(иначе)


def запуск(argv):
    if "--autostart" in argv:
        if not load_cfg().get("session"):
            print("Сначала войдите: запустите программу вручную и введите данные Telegram.")
        elif not load_cfg().get("agent_token"):
            print("Сначала вставьте ключ программы: «Вставить ключ программы.bat» (tg_agent.py --token).")
        else:
            autostart(True)
    elif "--no-autostart" in argv:
        autostart(False)
    elif "--proxy" in argv:
        c = load_cfg()
        if not c.get("session"):
            print("Сначала войдите: запустите программу вручную.")
        else:
            save_cfg(ask_proxy(c))
            перезапустить_фон("Сохранено. Запустите «Запустить Telegram для лид-центра.bat» (или «Включить автозапуск.bat»).")
    elif "--check" in argv:
        asyncio.run(check_connection())
    elif "--token" in argv:
        c = ask_token(load_cfg())
        if c.get("session"):
            перезапустить_фон("Запустите «Запустить Telegram для лид-центра.bat» (или «Включить автозапуск.bat»).")
    elif "--logout" in argv:
        autostart(False)
        stop_running()
        # 2.0.7: забываем только вход в Telegram (session). Ключ программы, прокси и api_id/api_hash остаются —
        # раньше стирался весь config.json, и после «Забыть вход» программа заново просила api_id/api_hash и ключ
        c = load_cfg()
        if c.get("session"):
            c.pop("session", None)
            save_cfg(c)
        print("Вход в Telegram забыт (ключ программы, прокси и api_id/api_hash сохранены).")
        print("Теперь запустите «Запустить Telegram для лид-центра.bat» и войдите: телефон и код из Telegram.")
        print("Старый сеанс в Telegram можно завершить: Настройки → Устройства → «Lead-centre (компьютер)».")
    else:
        asyncio.run(main())


if __name__ == "__main__":
    try:
        запуск(sys.argv)
    except KeyboardInterrupt:
        print("\nОстановлено.")
    except ConsoleInputUnavailable as e:
        log("Ручной ввод недоступен; настройки не удалены.")
        print("\n" + str(e))
        print("Телефон, код Telegram, пароль и ключи вводите только в окне программы, не в переписке.")
        sys.exit(2)
    except SystemExit:
        raise
    except BaseException as e:
        # не трассировка в окне, а понятная строка; подробности (без ключей) — в журнал
        try:
            log("Ошибка:", type(e).__name__, str(e)[:200])
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(traceback.format_exc() + "\n")
        except Exception:
            pass
        print("\nНе получилось: %s (%s)." % (type(e).__name__, str(e)[:160]))
        print("Подробности — в журнале: " + LOG + ". Пришлите последние строки журнала ведущему.")
        sys.exit(1)
