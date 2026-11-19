"""Legacy model contract via the existing budgeted GigaChat broker; no writes."""
import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request


class GigaChatError(Exception):
    pass


MODEL_BUDGET_MS = 30000
BROKER_TIMEOUT_S = 35


def messages(system, msgs, tools=None, tool_choice=None, model=None, max_tokens=None,
             timeout=BROKER_TIMEOUT_S, retries=None):
    # The provider key, OAuth token, cache and budget stay in the existing brain.
    url = os.environ.get('LEADBOT_GIGACHAT_BROKER',
                         'http://127.0.0.1:8081/internal/leadbot/completion')
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
            or parsed.path != '/internal/leadbot/completion' or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise GigaChatError('Неверный внутренний адрес GigaChat')
    token = os.environ.get('LEADBOT_SERVICE_TOKEN', '')
    if not token:
        raise GigaChatError('Не настроено соединение с GigaChat')
    system = system if isinstance(system, str) else '\n'.join(
        str(block.get('text', '')) for block in system if isinstance(block, dict))
    normalized = []
    for msg in msgs:
        content = msg.get('content', '')
        if isinstance(content, list):
            if any(not isinstance(b, dict) or b.get('type') != 'text' for b in content):
                raise GigaChatError('Вложение требует проверенного просмотра перед ответом')
            content = '\n'.join(b.get('text', '') for b in content)
        if not isinstance(content, str) or msg.get('role') not in ('user', 'assistant'):
            raise GigaChatError('Неподдерживаемая форма истории')
        normalized.append(dict(role=msg['role'], content=content))
    selected = None
    if tools:
        name = (tool_choice or {}).get('name')
        selected = next((t for t in tools if t.get('name') == name), None)
        if selected is None and len(tools) == 1:
            selected = tools[0]
        if selected is None:
            raise GigaChatError('Нужен однозначный контракт ответа')
    task = dict(messages=normalized)
    if selected:
        task['output_schema'] = selected['input_schema']
        task['output_instruction'] = 'Верни только JSON-объект аргументов по output_schema.'
    else:
        task['output_instruction'] = 'Верни только JSON-объект по контракту системного сообщения.'
    # The unified question uses the exact same prompt/cache key as the extension.
    broker_task = normalized[0]['content'] if not selected and len(normalized) == 1 \
        and normalized[0]['role'] == 'user' else json.dumps(task, ensure_ascii=False)
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise GigaChatError('Неверный срок проверки GigaChat')
    wait = min(BROKER_TIMEOUT_S, max(1, timeout))
    payload = dict(system=system, task=broker_task,
                   max_tokens=min(1200, max(1, int(max_tokens or 350))),
                   deadline_ms=min(MODEL_BUDGET_MS, int(wait * 1000) - 500))
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method='POST',
        headers={'Content-Type': 'application/json', 'X-Leadbot-Token': token})
    try:
        with urllib.request.urlopen(req, timeout=wait) as response:
            result = json.load(response)
        if not result.get('ok'):
            raise GigaChatError('GigaChat не подготовил проверяемый ответ')
        value = json.loads(result['text'])
        if not isinstance(value, dict):
            raise ValueError('object required')
    except (OSError, ValueError, KeyError, urllib.error.URLError) as exc:
        # No upstream body, credential, prompt or private history in exceptions.
        raise GigaChatError('GigaChat недоступен или нарушил контракт ответа') from None
    if selected:
        content = [dict(type='tool_use', id='gigachat-structured', name=selected['name'], input=value)]
    else:
        content = [dict(type='text', text=json.dumps(value, ensure_ascii=False))]
    return dict(content=content, model=result.get('model', ''),
                usage=result.get('usage', {}), provider='gigachat',
                cached=bool(result.get('cached')))
