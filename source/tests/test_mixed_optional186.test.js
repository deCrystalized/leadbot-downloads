const test=require('node:test');
const assert=require('node:assert/strict');
const {contactComment}=require('../ext/workflow.js');

const caveat='Дополнительно — по возможности посмотреть отопление; выполнение работ не подтверждено.';
test('optional inspection caveat survives the same CRM comment projection as contacts',()=>{
  const facts={comment_lines:[caveat,'Домофон: 53.']};
  const comment=contactComment('Заменить смеситель. Установить карниз.',facts);
  assert.ok(comment.endsWith(caveat+'\nДомофон: 53.'));
  assert.equal(contactComment(comment,facts),comment);
});

test('editing or deleting the conditional line restores it before the comment is prepared',()=>{
  const facts={comment_lines:[caveat]};
  const edited='Заменить смеситель. Отопление.';
  assert.equal(contactComment(edited,facts),edited+'\n'+caveat);
  assert.equal(contactComment('',facts),caveat);
});

test('withdrawn optional work is removed from an older editable draft',()=>{
  const facts={comment_lines:[],mixed_optional_work:{rule_id:'OWNER-MIXED-OPTIONAL-LOOK-20261023',extras:[],comment:''}};
  assert.equal(contactComment('Только заменить смеситель.\n'+caveat,facts),
               'Только заменить смеситель.');
});

test('changing the extra replaces only the managed line and retains operator notes',()=>{
  const line='Дополнительно — по возможности посмотреть перегородку; выполнение работ не подтверждено.';
  const facts={comment_lines:[line],mixed_optional_work:{rule_id:'OWNER-MIXED-OPTIONAL-LOOK-20261023',extras:[{subject:'partition'}],comment:line}};
  const result=contactComment('Повесить полку.\n'+caveat+'\nПозвонить перед приездом.',facts);
  assert.equal(result,'Повесить полку.\nПозвонить перед приездом.\n'+line);
  assert.equal(contactComment(result,facts),result);
});
