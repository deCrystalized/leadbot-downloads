"""Offline SIWC wire contract and original SSE decoder; no login or network.

Commercial eligibility, registered client and owner sign-in are prerequisites
outside this module. An API key is not a subscription credential. This module
cannot acquire one, authorize a call, or fall back to API billing.
"""
import copy

from research_pipeline import TOOLS

NAMESPACE = 'sources'
TRANSPORT_KIND = 'chatgpt_plan_sse_v1'
MAX_BYTES = 10 * 1024 * 1024


def project(payload):
    fields = {'model','store','parallel_tool_calls','service_tier','prompt_cache_options',
              'max_output_tokens','reasoning','instructions','input','tools','text'}
    if (not isinstance(payload,dict) or set(payload) != fields or payload.get('store') is not False
            or payload.get('reasoning') != {'effort': 'max'}):
        raise ValueError('Exact source-bound subscription options required')
    result = copy.deepcopy(payload)
    result.pop('max_output_tokens', None)
    result['stream'] = True
    tools = result.get('tools')
    if (not isinstance(tools, list) or any(not isinstance(t, dict) or t.get('type') != 'function'
            or t.get('name') not in TOOLS or t.get('strict') is not True for t in tools)):
        raise ValueError('Only the admitted read-only source functions are supported')
    result['tools'] = ([dict(type='namespace', name=NAMESPACE,
                           description='Read-only primary rules and full historical sources.', tools=tools)]
                       if tools else [])
    return result


def decode(raw):
    """Only completed terminal response objects can cross the durable boundary.

    Original bytes must have been fsynced first by Jobs. Deltas are not stitched
    into a repaired answer. A late limit/error invalidates earlier text.
    """
    from research_openai import strict_loads
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_BYTES:
        raise ValueError('Bounded original SSE bytes required')
    text = raw.decode('utf-8')
    text = text.replace('\r\n', '\n')
    if '\r' in text or not text.endswith('\n\n'):
        raise ValueError('Interrupted or malformed SSE stream')
    terminal, response_id, sequence = None, None, -1
    for frame in text.split('\n\n'):
        if not frame:
            continue
        event, data = None, []
        for line in frame.split('\n'):
            if line.startswith(':'):
                continue
            name, sep, value = line.partition(':')
            if not sep or name not in ('event', 'data'):
                raise ValueError('Unsupported SSE framing')
            value = value[1:] if value.startswith(' ') else value
            if name == 'event':
                if event is not None: raise ValueError('Repeated SSE event field')
                event = value
            else:
                data.append(value)
        if not data and event is None:
            continue  # Heartbeat comments are not model conclusions.
        if terminal is not None:
            raise ValueError('Data after terminal response')
        value = strict_loads('\n'.join(data))
        if (not isinstance(value, dict) or not isinstance(value.get('type'), str)
                or event is not None and event != value['type']):
            raise ValueError('SSE event/type mismatch')
        kind = value['type']
        number = value.get('sequence_number')
        if type(number) is not int or number <= sequence:
            raise ValueError('Missing or reordered event sequence')
        sequence = number
        if kind == 'error' or kind in ('response.failed', 'response.incomplete'):
            raise ValueError('Subscription stream failed; no retry or paid fallback')
        if not kind.startswith('response.'):
            raise ValueError('Unadmitted event type')
        event_id = value.get('response_id')
        if event_id is not None and (not isinstance(event_id,str) or not event_id
                or response_id is not None and event_id != response_id):
            raise ValueError('Event response identity changed')
        if event_id is not None:
            response_id = event_id
        response = value.get('response')
        if response is not None:
            if (not isinstance(response, dict) or not isinstance(response.get('id'), str)
                    or not response['id'] or response_id is not None and response_id != response['id']):
                raise ValueError('Response identity changed within stream')
            response_id = response['id']
        if kind == 'response.completed':
            if not isinstance(response, dict) or response.get('status') != 'completed':
                raise ValueError('A complete final response object is required')
            terminal = response
    if terminal is None:
        raise ValueError('No terminal completed response; no partial answer')
    return terminal
