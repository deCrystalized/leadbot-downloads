"""Responses API codec with an injected server transport, no implicit network.

No API key, endpoint or purchasing capability is stored here. Until a real
transport is separately configured and tested, mock results prove only wiring.
"""
import json
import uuid
import copy
import re
import math

from research_pipeline import MODELS, TOOLS, models_for, schema_matches
from research_media import image_inputs
from research_receipts import ProviderResult, StoppedProviderReceipt
import research_cache
import research_subscription
from experienced_dialogues import digest

MAX_OUTPUT_TOKENS = 32768  # Finite room for max-effort reasoning plus visible output.


class TransportError(ValueError):
    def __init__(self, *args, failure_code=None):
        super().__init__(*args)
        self.failure_code = failure_code if failure_code in ('provider_output_limit', 'provider_incomplete') else None


class RequestNotStarted(ValueError):
    """Trusted preflight stopped before any provider attempt or saved receipt."""


def strict_loads(raw):
    def pairs(items):
        value = {}
        for key,item in items:
            if key in value:
                raise ValueError('Duplicate JSON member')
            value[key] = item
        return value
    def constant(_value):
        raise ValueError('Nonfinite JSON value')
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=constant)


def tool_definitions(names):
    fields = dict(search_history=dict(query=dict(type='string', maxLength=600),
                                     direction=dict(type='string', enum=['mnc','kp','bt'])),
                  read_history=dict(case_id=dict(type='string', maxLength=200)),
                  search_rules=dict(query=dict(type='string', maxLength=600)),
                  read_rule=dict(rule_id=dict(type='string', maxLength=200)))
    if any(n not in TOOLS for n in names) or len(set(names)) != len(names):
        raise TransportError('Only distinct read-only source tools are allowed')
    return [dict(type='function', name=n, strict=True,
                 description='Read-only source tool. Historical examples are not current facts or primary rules.',
                 parameters=dict(type='object', properties=fields[n], required=list(fields[n]),
                                 additionalProperties=False)) for n in names]


def _schema(role, candidate_schema=None):
    strings = dict(type='array', items=dict(type='string'))
    references = dict(type='array', items=dict(type='string'), description=(
        'Exact references from source_references only: current:<client message ID>, '
        'rule:<already read primary ID>, history:<fully read case CID>. '
        'Never explanatory prose or bare IDs. Put short explanations in claim text or native note.'))
    if role == 'review':
        props = dict(kind=dict(type='string', enum=['review']), approved=dict(type='boolean'),
                     violations=strings, checked_claims=dict(type='array', items=dict(type='integer', minimum=0)), basis=references)
    else:
        claim = dict(type='object', properties=dict(scope=dict(type='string', enum=[
            'current_fact','policy','historical_example','uncertainty','question']), text=dict(type='string'), basis=references),
            required=['scope','text','basis'], additionalProperties=False)
        props = dict(kind=dict(type='string', enum=['draft']), reply=dict(type='string'),
                     evidence_ids=dict(type='array',items=dict(type='string'),description='Bare current client message IDs, without current: prefix.'),
                     basis=references, claims=dict(type='array', items=claim))
        if candidate_schema is not None:
            props['candidate'] = candidate_schema
    return dict(type='object', properties=props, required=list(props), additionalProperties=False)


def _branch_implies(branch, common):
    """Conservative structural proof, not a general JSON Schema simplifier.

    Unknown or missing constraints prevent removal. In particular bool enums
    cannot compare equal to integer enums through Python's True == 1 rule.
    """
    if not isinstance(branch, dict) or not isinstance(common, dict):
        return False
    canonical = lambda value: json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)
    for key, value in common.items():
        if key in ('description', 'title'):
            continue  # These annotations are retained on the resulting union.
        if key not in branch:
            return False
        actual = branch[key]
        if key == 'properties':
            if (not isinstance(value, dict) or not isinstance(actual, dict) or set(actual) != set(value)
                    or not all(_branch_implies(actual[name], child) for name, child in value.items())):
                return False
        elif key in ('items', 'additionalProperties') and isinstance(value, dict):
            if not _branch_implies(actual, value):
                return False
        elif key == 'required':
            if not isinstance(value, list) or not isinstance(actual, list) or not set(value) <= set(actual):
                return False
        elif key == 'enum':
            if (not isinstance(value, list) or not isinstance(actual, list)
                    or not {canonical(v) for v in actual} <= {canonical(v) for v in value}):
                return False
        elif key in ('minLength', 'minItems', 'minimum', 'maxLength', 'maxItems', 'maximum'):
            if (type(value) not in (int, float) or type(actual) not in (int, float)
                    or not math.isfinite(value) or not math.isfinite(actual)
                    or (key in ('minLength', 'minItems', 'maxLength', 'maxItems')
                        and (type(value) is not int or type(actual) is not int or value < 0 or actual < 0))
                    or (actual < value if key.startswith('min') else actual > value)):
                return False
        elif canonical(actual) != canonical(value):
            return False
    return True


def compact_wire_schema(schema, *, _root=True):
    """Remove only a proven redundant parent around nested unchanged anyOf.

    The bound native contract and every branch remain intact. The response
    root remains an object; this adds no allOf, refs, defaults or repair path.
    """
    result = copy.deepcopy(schema)
    if not isinstance(result, dict):
        return result
    for key in ('properties',):
        if isinstance(result.get(key), dict):
            result[key] = {name: compact_wire_schema(child, _root=False) for name, child in result[key].items()}
    for key in ('items', 'additionalProperties'):
        if isinstance(result.get(key), dict):
            result[key] = compact_wire_schema(result[key], _root=False)
    for key in ('anyOf', 'oneOf', 'allOf'):
        if isinstance(result.get(key), list):
            result[key] = [compact_wire_schema(child, _root=False) for child in result[key]]
    branches = result.get('anyOf')
    common = {key: value for key, value in result.items() if key != 'anyOf'}
    if (not _root and isinstance(branches, list) and branches
            and set(common) - {'description', 'title'}
            and all(_branch_implies(branch, common) for branch in branches)):
        return {**{key: value for key, value in common.items() if key in ('description', 'title')}, 'anyOf': branches}
    return result


class ResponsesTransport:
    def __init__(self, request, ledger, *, media_resolver=None, funding='api'):
        if not callable(request):
            raise TransportError('An explicitly configured trusted server transport is required')
        if funding not in ('api', 'chatgpt_plan'):
            raise TransportError('Explicit funding mode required; no automatic fallback')
        self.request, self.ledger = request, ledger
        self.funding = funding
        self.media_resolver = media_resolver
        self.pending_tool = None
        self.seen_call_ids = set()

    def __call__(self, role, packet, tools):
        models = models_for(packet.get('profile'))
        if role not in models or packet.get('model') != models[role]:
            raise TransportError('Requested role/model mismatch; no fallback')
        current = packet.get('input', {}).get('current', {})
        if not current.get('owner_id') or not current.get('dialogue_id'):
            raise TransportError('Verified billing/dialogue scope is required')
        scope = dict(owner=current['owner_id'],dialogue=current['dialogue_id'],role=role)
        definitions = tool_definitions(tools)
        purpose = packet.get('purpose')
        purpose_module = None
        if purpose is not None:
            import research_vision
            import research_form
            purpose_module = {research_vision.PURPOSE:research_vision,research_form.PURPOSE:research_form}.get(purpose)
            if purpose_module is None or tools:
                raise TransportError('Unadmitted visual purpose or tool capability')
        remaining = packet.get('remaining_seconds', 120)
        if isinstance(remaining, bool) or not isinstance(remaining,(int,float)) or not 0 < remaining <= 300:
            raise TransportError('Invalid remaining time budget')
        reusable = {k:v for k,v in packet['input'].get('research',{}).items() if k not in ('draft','last_tool_result','call_budget')}
        changing = dict(current=current, source_references=packet['input'].get('source_references', []),
                        draft=packet['input'].get('research',{}).get('draft'),
                        last_tool_result=packet['input'].get('research',{}).get('last_tool_result'))
        budget = packet['input'].get('research', {}).get('call_budget')
        if budget is not None:
            changing['call_budget'] = budget
        # Resolve before a billable request/unknown-usage receipt is reserved.
        # An absent or changed original never degrades to a caption-only call.
        pixels = image_inputs(current, self.media_resolver)
        control, core = research_cache.core_input(packet['instructions'])
        payload = dict(model=models[role], store=False, parallel_tool_calls=False,service_tier='default',
            prompt_cache_options=dict(mode='explicit',ttl='30m'),
            max_output_tokens=MAX_OUTPUT_TOKENS,  # Incomplete output is still blocked, never retried or repaired.
            reasoning=dict(effort='max'), instructions=control,
            input=[core]+[dict(role='user', content=[dict(type='input_text',text=json.dumps(part,ensure_ascii=False,sort_keys=True))]
                        + (pixels if index == 1 else []))
                   for index,part in enumerate((dict(research=reusable),changing))],
            tools=definitions, text=dict(format=dict(type='json_schema', name='source_'+role,
                       strict=True, schema=_schema(role,current.get('candidate_contract',{}).get('schema')))))
        if self.pending_tool is not None:
            pending = self.pending_tool
            research = packet['input'].get('research', {})
            if (pending['binding'] != digest([role,packet.get('profile'),current,packet['instructions']])
                    or research.get('last_tool_request') != pending['request']
                    or not isinstance(research.get('last_tool_result'), dict)):
                raise TransportError('Missing or changed source result for the exact pending call')
            # Stateless Responses continuation: preserve the entire phase
            # transcript, including opaque provider reasoning items. These
            # bytes are never interpreted as explanations or current facts.
            result = dict(result=research['last_tool_result'],
                          source_references=packet['input'].get('source_references', []))
            if budget is not None:
                result['call_budget'] = budget
            payload['input'] = copy.deepcopy(pending['input']) + copy.deepcopy(pending['output']) + [
                dict(type='function_call_output',call_id=pending['call_id'],
                     output=json.dumps(result,ensure_ascii=False,sort_keys=True,allow_nan=False))]
        research_cache.validate(payload)
        if self.funding == 'chatgpt_plan':
            payload = research_subscription.project(payload)
        if purpose is not None:
            payload['text']['format']['schema'] = purpose_module.schema(role)
        if self.funding == 'api':
            payload['text']['format']['schema'] = compact_wire_schema(payload['text']['format']['schema'])
        attempt = 'attempt-' + uuid.uuid4().hex
        def receipt(value, *, failed=False):
            tier=value.get('service_tier') if isinstance(value.get('service_tier'),str) else None
            status=value.get('status')
            usage=value.get('usage') if value.get('model')==models[role] else None
            incomplete=value.get('incomplete_details')
            if (status=='incomplete' and isinstance(incomplete,dict) and incomplete.get('reason')=='max_output_tokens'
                    and isinstance(usage,dict) and usage.get('input_tokens')==0 and usage.get('output_tokens')==0):
                # A nonempty admitted prompt exhausted a generation budget.
                # Preserve the original receipt, but do not call its zero
                # counters a verified free request or invent replacement usage.
                usage=None
            try:
                self.ledger.add(value.get('id') or attempt,models[role],
                    usage,
                    status=status if not failed and status in ('completed','incomplete','failed') else 'failed',
                    scope=scope,service_tier=tier,funding=self.funding)
            except ValueError:
                # Invalid counts or a conflicting response ID still represent
                # a real attempt. Keep the first immutable receipt; the new
                # outcome is unknown, never a dropped/zero-dollar call.
                self.ledger.add(attempt,models[role],None,status='failed',scope=scope,service_tier=tier,funding=self.funding)
                raise TransportError('Invalid or conflicting provider usage receipt; new cost unknown') from None
            return tier
        try:
            response = self.request(payload, remaining)  # One attempt within the original remaining deadline.
        except RequestNotStarted:
            raise TransportError('Trusted research preflight stopped before provider; no new billable attempt') from None
        except StoppedProviderReceipt as exc:
            # The durable requester has already stopped this job. Use only its
            # original billing fields; never return or review its model candidate.
            attempt = exc.billing_attempt_id or attempt
            if isinstance(exc.billing_response,dict):
                receipt(exc.billing_response,failed=not 200<=exc.billing_metadata['http_status']<300)
            else:
                self.ledger.add(attempt,models[role],None,status='failed',scope=scope,
                                service_tier=None,funding=self.funding)
            raise TransportError('Original receipt saved; job stopped before ACK; no retry or response acceptance') from None
        except Exception as exc:
            self.ledger.add(attempt, models[role], None, status='failed', scope=scope,service_tier=None,funding=self.funding)
            raise TransportError('Provider request failed; billing result unknown; no retry') from None
        if isinstance(response,ProviderResult) and not 200<=response.metadata['http_status']<300:
            receipt(response,failed=True)
            raise TransportError('Provider rejected the HTTP request; no retry or fallback')
        if (isinstance(response,ProviderResult)
                and (response.metadata['content_type']=='event_stream') != (self.funding=='chatgpt_plan')):
            receipt(response,failed=True)
            raise TransportError('Response transport differs from admitted funding; no fallback')
        if not isinstance(response, dict) or response.get('model') != models[role]:
            self.ledger.add(attempt, models[role], None, status='failed', scope=scope,service_tier=None,funding=self.funding)
            raise TransportError('Unverified provider response/model; no fallback')
        status = response.get('status')
        tier=receipt(response)
        if status != 'completed':
            code = ('provider_output_limit' if status == 'incomplete' and isinstance(response.get('incomplete_details'), dict)
                    and response['incomplete_details'].get('reason') == 'max_output_tokens' else 'provider_incomplete')
            raise TransportError('Incomplete provider response is not permission', failure_code=code)
        if tier != 'default':
            raise TransportError('Actual provider tier is missing or differs from admitted Standard; no retry')
        output = response.get('output')
        if not isinstance(output, list):
            raise TransportError('Missing provider output')
        # Reasoning items are neither a reply nor extra output to bill twice.
        relevant = [x for x in output if isinstance(x,dict) and x.get('type') != 'reasoning']
        if len(relevant) != 1:
            raise TransportError('Exactly one source call or stage conclusion is required')
        result = relevant[0]
        if result.get('type') == 'function_call':
            if self.funding == 'chatgpt_plan' and result.get('namespace') != research_subscription.NAMESPACE:
                raise TransportError('Source function namespace is missing or changed')
            if result.get('name') not in tools:
                raise TransportError('Provider selected an unadvertised tool')
            try:
                args = strict_loads(result['arguments'])
            except (ValueError,TypeError,KeyError):
                raise TransportError('Invalid function arguments; no JSON repair') from None
            if not isinstance(args,dict):
                raise TransportError('Function arguments must be an object')
            call_id = result.get('call_id')
            if (not isinstance(call_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}',call_id)
                    or call_id in self.seen_call_ids):
                raise TransportError('Missing or repeated function call identity')
            self.seen_call_ids.add(call_id)
            self.pending_tool = dict(binding=digest([role,packet.get('profile'),current,packet['instructions']]),
                request=dict(name=result['name'],arguments=copy.deepcopy(args)),call_id=call_id,
                input=copy.deepcopy(payload['input']),output=copy.deepcopy(output))
            return dict(kind='tool', name=result['name'], arguments=args)
        if (result.get('type') != 'message' or result.get('role') != 'assistant'
                or result.get('status') != 'completed'):
            raise TransportError('Unknown or incomplete output item')
        content = result.get('content')
        if not isinstance(content,list) or len(content) != 1 or content[0].get('type') != 'output_text':
            raise TransportError('Refusal or nontext conclusion is not approval')
        try:
            conclusion = strict_loads(content[0]['text'])
        except (ValueError,TypeError,KeyError):
            raise TransportError('Invalid conclusion JSON; no repair') from None
        expected = 'review' if role == 'review' else ('intake_form' if purpose=='intake_form_v1' else 'visual_observation' if purpose is not None else 'draft')
        if not isinstance(conclusion,dict) or conclusion.get('kind') != expected:
            raise TransportError('Wrong stage conclusion')
        original_schema = (purpose_module.schema(role) if purpose_module is not None else
                           _schema(role,current.get('candidate_contract',{}).get('schema')))
        if not schema_matches(conclusion,original_schema):
            raise TransportError('Original conclusion does not match the admitted stage schema; no repair')
        self.pending_tool = None
        return conclusion  # The core validates source scope, fields and complete review coverage.
