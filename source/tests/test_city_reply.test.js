'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const replies=require('../ext/city-reply');

test('a branch acknowledgement is consumed without a client promise or a popup',()=>{
 const r=replies.select([{id:15,at:100,text:'сек',from:'Dispatcher'}],{seen:99});
 assert.equal(r.latest,null); assert.equal(r.cursor.seen,100);
 assert.equal(replies.select([{id:15,at:100,text:'сек'}],r.cursor).latest,null);
 for(const text of ['Сек.','сейчас уточню','Ок','👍','минутку']) assert.equal(replies.describe(text).notify,false,text);
});
test('unsorted polling and reloads cannot repeat the same reply',()=>{
 const rows=[{id:3,at:103,text:'Мастер едет'},{id:2,at:102,text:'сек'}];
 const a=replies.select(rows,{seen:101}); assert.equal(a.latest.id,3);assert.equal(a.cursor.seen,103);
 assert.equal(replies.select(rows,JSON.parse(JSON.stringify(a.cursor))).latest,null);
 const b=replies.select([{id:4,at:103,text:'Мастер позвонит'}],a.cursor);assert.equal(b.latest.id,4);
});
test('only explicit facts become a client draft; delay is not an ETA',()=>{
 assert.match(replies.describe('мастер задерживается на 10 минут').reply,/задерживается на 10/);
 assert.doesNotMatch(replies.describe('мастер задерживается на 10 минут').reply,/через/);
 assert.match(replies.describe('мастер будет через 20 минут').reply,/через 20/);
 assert.equal(replies.describe('Мастер едет').reply,'Мастер едет к вам.');
 for(const text of ['Мастер не выехал','Будет через 20 минут?','Наверное приедет через 10 минут','Если мастер будет через 10 минут','Клиент едет','Уточняю'])assert.equal(replies.describe(text).reply,'',text);
 assert.equal(replies.describe('сек').reply,'');
});
test('an edited branch answer replaces its earlier meaning once',()=>{
 const a=replies.select([{id:1,at:101,text:'Мастер едет'}],{seen:100});
 const b=replies.select([{id:1,at:101,text:'Мастер не выехал'}],a.cursor);
 assert.equal(b.latest.text,'Мастер не выехал');assert.equal(replies.describe(b.latest.text).reply,'');
 assert.equal(replies.select([{id:1,at:101,text:'Мастер не выехал'}],b.cursor).latest,null);
});
test('seconds and milliseconds share a cursor; missing dates use stable message identity',()=>{
 const a=replies.select([{id:1,at:1700000000000,text:'Мастер едет'}],{seen:1699999999});
 assert.equal(a.cursor.seen,1700000000);
 assert.equal(replies.select([{id:1,at:1700000000,text:'Мастер едет'}],a.cursor).latest,null);
 const b=replies.select([{id:2,text:'Нужно проверить адрес'}],a.cursor);assert.equal(b.latest.id,2);
 assert.equal(replies.select([{id:2,text:'Нужно проверить адрес'}],b.cursor).latest,null);
});
