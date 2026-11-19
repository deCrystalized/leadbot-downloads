"""Pure CRM reference hints; the unscoped raw-file batch command is retired.

A hint is not proof of creation, customer identity or success. Callers must
admit sources before supplying messages. The authenticated native reader owns
new body access; this module cannot open a corpus or write index outputs.
The pinned audit-source253-v3/project/tools snapshot retains the original batch tool.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'leadbot/brain'))
import crm_evidence

URL = re.compile(r"https?://(?P<dir>kp|bt|mnc)-lead-centre\.ru/admin/domain/customer-request/update\?id=(?P<id>\d{6,8})(?!\d)", re.I)
LABEL = re.compile(r"\b(?:заявк\w*|заказ\w*)\s*(?:CRM|№|#|:)?\s*(\d{6,8})(?!\d)", re.I)

def reference_hints(message):
    """The production parser owns staff-note syntax; all results remain candidates."""
    text = str(message.get('body') or message.get('text') or '')
    hints = [(m['id'], 'explicit_crm_card_url', m['dir']) for m in URL.finditer(text)]
    hints += [(m[1], 'labelled_request_id', '') for m in LABEL.finditer(text)]
    seen = {rid for rid, _, _ in hints}
    for row in crm_evidence.note_references([message]):
        rid = row['request_id_candidate']
        if rid not in seen:
            hints.append((rid, 'operator_crm_note_candidate', ''))
            seen.add(rid)
    return list(dict.fromkeys(hints))



def main():
    raise RuntimeError('Unscoped raw-file CRM indexer retired; use admitted guarded source access')


if __name__ == '__main__':
    main()
