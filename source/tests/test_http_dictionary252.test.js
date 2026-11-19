'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {событие}=require('../extension-server/vps/brain_http');
const req=(url,rawHeaders=[])=>({url,method:'GET',rawHeaders,headers:{},socket:{remoteAddress:'127.0.0.1'}});
test('a legal constructor header is represented without inherited-property collisions',()=>{
 const e=событие(req('/', ['constructor','a','Constructor','b']),Buffer.alloc(0),'synthetic',0);
 assert.deepEqual(e.multiValueHeaders.constructor,['a','b']);assert.equal(e.headers.constructor,'a, b');
});
test('legal query property names retain all values and the final value',()=>{
 const e=событие(req('/?constructor=a&constructor=b&toString=x&hasOwnProperty=y'),Buffer.alloc(0),'synthetic',0);
 assert.deepEqual(e.multiValueQueryStringParameters.constructor,['a','b']);
 assert.equal(e.queryStringParameters.constructor,'b');assert.equal(e.queryStringParameters.toString,'x');
 assert.equal(e.queryStringParameters.hasOwnProperty,'y');
});
test('prototype mutation names remain excluded in headers and query',()=>{
 const e=событие(req('/?__proto__=x&normal=ok', ['__proto__','x']),Buffer.alloc(0),'synthetic',0);
 assert.equal(Object.hasOwn(e.queryStringParameters,'__proto__'),false);
 assert.equal(Object.hasOwn(e.multiValueHeaders,'__proto__'),false);
 assert.equal(e.queryStringParameters.normal,'ok');assert.equal(Object.getPrototypeOf(e.headers),Object.prototype);
});
