const test=require('node:test');
const assert=require('node:assert/strict');
const {contactComment}=require('../ext/workflow.js');

test('the CRM comment retains the full server-proven code and venue',()=>{
  const facts={comment_lines:['Домофон: 108#742.','Ориентир со слов клиента: «Зал ожидания, отдел Смартфон 159».']};
  const result=contactComment('Ремонт мебели. Объявление: «Мастер».',facts);
  assert.ok(result.includes('Домофон: 108#742.'));
  assert.ok(result.includes('отдел Смартфон 159'));
  assert.ok(result.includes('Ремонт мебели. Объявление: «Мастер».'));
  assert.equal(contactComment(result,facts),result);
});

test('an old truncated code does not replace the complete server line',()=>{
  assert.equal(contactComment('Домофон: 108.',{comment_lines:['Домофон: 108#742.']}),'Домофон: 108.\nДомофон: 108#742.');
});

test('missing contact facts preserve the original comment',()=>{
  assert.equal(contactComment('Ремонт.',null),'Ремонт.');
  assert.equal(contactComment('Ремонт.',{comment_lines:[null,{},'',123]}),'Ремонт.');
});
