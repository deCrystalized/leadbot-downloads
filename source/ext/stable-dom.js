/* Keyed in-place rendering for the spectator. No polling-induced DOM replacement. */
const LC_STABLE_DOM=(()=>{
  const events=new WeakMap();
  function factory(base,onError){return (tag,attrs={},...children)=>{
    const plain={},handlers={};for(const [name,value]of Object.entries(attrs))if(name.startsWith('on')&&typeof value==='function')handlers[name.slice(2)]=value;else plain[name]=value;
    const node=base(tag,plain,...children),bound={};
    for(const [name,handler]of Object.entries(handlers)){
      bound[name]=event=>{try{Promise.resolve(handler(event)).catch(onError)}catch(error){onError(error)}};
      node.addEventListener(name,bound[name]);
    }
    events.set(node,bound);return node;
  }}
  const key=n=>n.nodeType===1?(n.getAttribute('data-observer-id')||n.getAttribute('data-assistant-focus')||n.getAttribute('data-assistant-disclosure')||n.getAttribute('data-render-key')||''):'';
  const same=(a,b)=>a.nodeType===b.nodeType&&a.nodeName===b.nodeName&&key(a)===key(b);
  function patch(node,next){
    if(node.nodeType===3){if(node.nodeValue!==next.nodeValue)node.nodeValue=next.nodeValue;return}
    if(node.nodeType!==1)return;
    for(const attr of [...node.attributes])if(!next.hasAttribute(attr.name))node.removeAttribute(attr.name);
    for(const attr of next.attributes)if(node.getAttribute(attr.name)!==attr.value)node.setAttribute(attr.name,attr.value);
    for(const property of ['disabled','checked','selected','indeterminate'])if(property in next&&node[property]!==next[property])node[property]=next[property];
    if(['INPUT','TEXTAREA','SELECT'].includes(node.nodeName)&&node.value!==next.value)node.value=next.value;
    if(events.has(next)){
      for(const [name,handler]of Object.entries(events.get(node)||{}))node.removeEventListener(name,handler);
      for(const [name,handler]of Object.entries(events.get(next)))node.addEventListener(name,handler);
      events.set(node,events.get(next));
    }
    children(node,[...next.childNodes]);
  }
  function children(parent,nextNodes){
    const old=[...parent.childNodes],used=new Set();let cursor=parent.firstChild;
    for(const next of nextNodes){
      const id=key(next);
      const found=id?old.find(n=>!used.has(n)&&key(n)===id&&same(n,next))
        :cursor&&!used.has(cursor)&&same(cursor,next)?cursor:null;
      const node=found||next;
      if(found){used.add(found);patch(found,next)}
      if(node!==cursor)parent.insertBefore(node,cursor);
      cursor=node.nextSibling;
    }
    for(const node of old)if(!used.has(node)&&node.parentNode===parent)node.remove();
  }
  return {factory,children};
})();
if(typeof module!=='undefined'&&module.exports)module.exports=LC_STABLE_DOM;
