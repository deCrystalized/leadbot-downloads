"""Explicit core-only cache boundary, not a cache-hit or savings assertion."""
import json

from experienced_dialogues import digest


def core_input(instructions):
    core = json.loads(instructions)
    if not isinstance(core, dict) or core.get('role') not in ('research', 'review'):
        raise ValueError('Trusted stage instructions required')
    control = dict(role=core['role'], profile=core['profile'], cache_contract='explicit_core_v1')
    return (json.dumps(control, ensure_ascii=False, sort_keys=True),
            dict(role='developer', content=[dict(type='input_text', text=instructions,
                 prompt_cache_breakpoint=dict(mode='explicit'))]))


def validate(payload):
    options = payload.get('prompt_cache_options')
    if options == dict(mode='implicit', ttl='30m'):
        return  # Historical admitted requests retain their original representation.
    if options != dict(mode='explicit', ttl='30m'):
        raise ValueError('Only the admitted 30-minute cache policy is supported')
    control = json.loads(payload['instructions'])
    items = payload['input']
    if not isinstance(items, list) or not items:
        raise ValueError('Missing core input')
    first = items[0]
    if (not isinstance(first, dict) or first.get('role') != 'developer'
            or set(first) != {'role', 'content'} or not isinstance(first['content'], list)
            or len(first['content']) != 1):
        raise ValueError('The first item must be the stable developer core')
    block = first['content'][0]
    if (not isinstance(block, dict) or set(block) != {'type', 'text', 'prompt_cache_breakpoint'}
            or block['type'] != 'input_text' or block['prompt_cache_breakpoint'] != dict(mode='explicit')):
        raise ValueError('Exact explicit core boundary required')
    core = json.loads(block['text'])
    if (not isinstance(core, dict) or not isinstance(control, dict)
            or control != dict(role=core.get('role'), profile=core.get('profile'), cache_contract='explicit_core_v1')):
        raise ValueError('Stage/core binding changed')
    def has_marker(value):
        if isinstance(value, dict):
            return 'prompt_cache_breakpoint' in value or any(has_marker(x) for x in value.values())
        return isinstance(value, list) and any(has_marker(x) for x in value)
    if has_marker(items[1:]):
        raise ValueError('Changing client/source/tool content cannot acquire a cache write')


def diagnostics(payload):
    """Hashes reveal partition changes, never token counts or cache hits."""
    validate(payload)
    explicit = payload['prompt_cache_options']['mode'] == 'explicit'
    core = payload['input'][0] if explicit else payload['instructions']
    return dict(mode=payload['prompt_cache_options']['mode'], ttl='30m',
                core_hash=digest(core), partition_hash=digest([
                    payload['model'], payload.get('reasoning'), payload.get('tools'),
                    payload.get('text'), payload['instructions'], core]),
                measured_hit=False, dynamic_schema_can_change_partition=True)
