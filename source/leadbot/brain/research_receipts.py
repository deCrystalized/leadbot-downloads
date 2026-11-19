"""Safe transport evidence separate from unchanged provider JSON bytes."""
import re


def transport_metadata(value):
    if (not isinstance(value, dict) or set(value)-{'schema','http_status','content_type','request_id'}
            or value.get('schema') != 1 or type(value.get('http_status')) is not int
            or not 100 <= value['http_status'] <= 599 or value.get('content_type') not in ('json','other','event_stream')):
        raise ValueError('Invalid safe HTTP receipt metadata')
    if 'request_id' in value and not re.fullmatch(r'req_[A-Za-z0-9_-]{1,128}', value['request_id']):
        raise ValueError('Invalid safe provider request identity')
    return dict(value)


class HTTPReceipt(bytes):
    transport_kind = 'openai_https_v1'
    def __new__(cls, raw, metadata):
        value = super().__new__(cls, raw)
        value._metadata = transport_metadata(metadata)
        return value

    @property
    def metadata(self):
        return dict(self._metadata)


class SSEReceipt(HTTPReceipt):
    transport_kind = 'chatgpt_plan_sse_v1'


def validate_kind(kind, metadata):
    metadata = transport_metadata(metadata)
    if (kind not in ('openai_https_v1', 'chatgpt_plan_sse_v1')
            or kind == 'openai_https_v1' and metadata['content_type'] == 'event_stream'
            or kind == 'chatgpt_plan_sse_v1' and 200 <= metadata['http_status'] < 300
               and metadata['content_type'] != 'event_stream'):
        raise ValueError('Transport kind/content type mismatch')
    return metadata


class ProviderResult(dict):
    def __init__(self, value, metadata):
        super().__init__(value)
        self._metadata = transport_metadata(metadata)

    @property
    def metadata(self):
        return dict(self._metadata)


class StoppedProviderReceipt(ValueError):
    """Trusted durable billing evidence; never a usable model response.

    Only the durable requester constructs this marker after original raw and
    transport hashes have been saved. Its cost fields grant no ACK or action.
    """
    billing_response = None
    billing_metadata = None
    billing_attempt_id = None


class HTTPFailure(ValueError):
    def __init__(self, category, partial=b''):
        if category not in ('network','deadline','response_too_large','credential_reflected','invalid_http_metadata'):
            category = 'network'
        self.category = category
        self.partial = partial if isinstance(partial,bytes) else b''
        super().__init__('HTTP provider attempt stopped ('+category+'); no retry')
