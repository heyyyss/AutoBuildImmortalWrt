const fs = require("fs"), vm = require("vm"), assert = require("node:assert/strict");
let now=0, next=0;
const timers=new Map();
const context={
  setTimeout(fn,delay){let id=++next;timers.set(id,{fn,due:now+delay});return id},
  clearTimeout(id){timers.delete(id)}
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(__dirname+"/../web/display-gate.js","utf8")+";globalThis.Gate=N1DisplayGate",context);
function advance(ms){now+=ms;for(const [id,t] of [...timers])if(t.due<=now){timers.delete(id);t.fn()}}
(async()=>{
 const gate=new context.Gate();
 let done=false,t=gate.begin(true);gate.wait(t).then(()=>done=true);
 gate.session({type:"hello",sessionActive:true});advance(2000);await Promise.resolve();assert(!done);
 gate.session({type:"session",sessionActive:false});advance(7000);await Promise.resolve();assert(!done);
 gate.session({type:"session",sessionActive:true});advance(1199);await Promise.resolve();assert(!done);
 advance(1);await Promise.resolve();assert(done);assert.equal(gate.ticket,null);
 t=gate.begin(false);done=false;gate.wait(t).then(()=>done=true);
 gate.session({type:"session",sessionActive:true});advance(600);
 gate.session({type:"session",sessionActive:false});advance(1000);await Promise.resolve();assert(!done);
 gate.session({type:"session",sessionActive:true});advance(1200);await Promise.resolve();assert(done);
 t=gate.begin(false);done=false;gate.wait(t).then(()=>done=true);advance(30000);await Promise.resolve();assert(done);
 t=gate.begin(true);gate.cancel(t);await gate.wait(t);assert.equal(gate.ticket,null);
 console.log("Display hold survives stale hello and reconnect interruptions, releases after live, and times out safely.");
})().catch(e=>{console.error(e);process.exitCode=1});
