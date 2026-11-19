'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),dom=require('../ext/stable-dom');
class Node {
 constructor(name,text=''){this.nodeName=name;this.nodeType=name==='#text'?3:1;this.nodeValue=text;this.childNodes=[];this.parentNode=null;this.attrs=new Map();this.listeners=new Map();this.moves=0;this.value='';this.scrollTop=17}
 get attributes(){return [...this.attrs].map(([name,value])=>({name,value}))}get firstChild(){return this.childNodes[0]||null}get nextSibling(){return this.parentNode?.childNodes[this.parentNode.childNodes.indexOf(this)+1]||null}
 getAttribute(k){return this.attrs.get(k)??null}hasAttribute(k){return this.attrs.has(k)}setAttribute(k,v){this.attrs.set(k,String(v))}removeAttribute(k){this.attrs.delete(k)}
 insertBefore(node,ref){if(node.parentNode)node.remove();this.childNodes.splice(ref?this.childNodes.indexOf(ref):this.childNodes.length,0,node);node.parentNode=this;this.moves++}
 remove(){if(this.parentNode){const p=this.parentNode;p.childNodes.splice(p.childNodes.indexOf(this),1);this.parentNode=null}}
 addEventListener(k,v){if(!this.listeners.has(k))this.listeners.set(k,new Set());this.listeners.get(k).add(v)}removeEventListener(k,v){this.listeners.get(k)?.delete(v)}
}
const base=(tag,attrs={},...kids)=>{const n=new Node(tag.toUpperCase());for(const [k,v]of Object.entries(attrs))if(v!==false&&v!=null)n.setAttribute(k,v);if('value'in attrs)n.value=attrs.value;for(const k of kids.flat())if(k!=null&&k!==false&&k!=='')n.insertBefore(k instanceof Node?k:new Node('#text',String(k)),null);return n};
test('identical polls retain actual card, message and scroll nodes without moves',()=>{
 const root=base('div'),h=dom.factory(base,e=>{throw e});const tree=()=>h('article',{'data-observer-id':'c1'},h('div',{class:'observer-messages'},'Hello'));
 dom.children(root,[tree()]);const card=root.firstChild,box=card.firstChild,msg=box.firstChild;const before=[root.moves,card.moves,box.moves];
 for(let i=0;i<20;i++)dom.children(root,[tree()]);
 assert.equal(root.firstChild,card);assert.equal(card.firstChild,box);assert.equal(box.firstChild,msg);assert.equal(box.scrollTop,17);assert.deepEqual([root.moves,card.moves,box.moves],before);
});
test('keyed reordering preserves existing conversations and only removes departed cards',()=>{
 const root=base('div'),h=dom.factory(base,e=>{throw e}),card=id=>h('article',{'data-observer-id':id},id);
 dom.children(root,[card('a'),card('b')]);const [a,b]=root.childNodes;
 dom.children(root,[card('b'),card('a'),card('c')]);assert.equal(root.childNodes[0],b);assert.equal(root.childNodes[1],a);
 dom.children(root,[card('b')]);assert.equal(root.firstChild,b);assert.equal(root.childNodes.length,1);
});
test('retained buttons invoke only the fresh handler once',()=>{
 const root=base('div'),seen=[],h=dom.factory(base,e=>{throw e}),view=value=>h('button',{'data-assistant-focus':'takeover',onclick:()=>seen.push(value)},String(value));
 dom.children(root,[view(1)]);const button=root.firstChild;dom.children(root,[view(2)]);assert.equal(root.firstChild,button);
 assert.equal(button.listeners.get('click').size,1);for(const fn of button.listeners.get('click'))fn({});assert.deepEqual(seen,[2]);
});
test('text updates keep a focused input node and stable neighbouring card',()=>{
 const root=base('div'),h=dom.factory(base,e=>{throw e});const view=value=>[h('input',{'data-assistant-focus':'search',value}),h('article',{'data-observer-id':'c'},value)];
 dom.children(root,view('a'));const [input,card]=root.childNodes;input.selectionStart=1;
 dom.children(root,view('ab'));assert.equal(root.firstChild,input);assert.equal(input.value,'ab');assert.equal(input.selectionStart,1);assert.equal(root.childNodes[1],card);assert.equal(card.firstChild.nodeValue,'ab');
});
