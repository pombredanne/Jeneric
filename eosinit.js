/*
 - the general object structure, 
 - serializer init, 
 - comet init 
 - terminal creation
    - set vm.parent to ""
    - set vm.uri to "~"
 - some basic types and security??? -> additional files for vm.load()
    - getMethodList ?? describeObject ?? or is it security code??
 - create a DIV to bind terminal object to.
*/

/*

TODO: cache .jn files, do not load them every time!

*/

DEBUG=0;

// parameters for STOMP connection
E_SERVER = "localhost";
E_PORT = 61613;
HUB_PATH = "/hub";
ANNOUNCE_PATH = "/announce";
RQ_RESEND_INTERVAL = 10000; // milliseconds to wait before request send retries
ACK_TIMEOUT = 60000; // milliseconds before give up resending
MAX_WINDOW_SIZE = 60000; // ms. max window size for ACKs to remember
KEY_LENGTH = 80; // bytes stringkey length
// GENERAL INIT part
KCONFIG = {autorestore: false}; // kernel configuration

_terminal_vm = new Jnaric();

_terminal_vm.name = "terminal"+(new Date()).getTime(); // TODO! get real terminal name!!! (somehow??)
_terminal_vm.TypeURI = "terminal"; // no real URI
_terminal_vm.SecurityURI = "terminal"; // no IPC for terminal at all
_terminal_vm.parent = "/guest"; // the server root?? username?? FUCK!!! XXX TODO !!!!!!!!!!!!
                          // the parent should be our username - REATTACH PARENT when authenticated!!
_terminal_vm.uri = "~";//_terminal_vm.parent + "/"+name; // rewrite THIS when authenticated...!!
_terminal_vm.serID = -1; // can never be serialized
_terminal_vm.childList = {}; // TODO: init the CL from somewhere !!!

_terminal_vm.global.initIPCLock = true; // THIS to be flushed by security validateRequest method init
_terminal_vm.global.wakeupIPCLock = false; 


// BINDING part
var dmb = document.createElement("DIV");
dmb.style.width = "100%";
document.body.appendChild(dmb);

_dmb = new __HTMLElement(_terminal_vm, "DIV" );
_dmb.___link = dmb;

_terminal_vm.bind_dom(_dmb); // TODO bind to fake DOM element since it is currently impossible to serialize DOM-enabled elements
_terminal_vm.bind_om(); // bind the protected EOS object model
_terminal_vm.bind_terminal();


// TWEAKINIT part

_terminal_vm.load("anarchic.jn");



// write the object!
__eos_objects["terminal"] = _terminal_vm;



// NOW CREATE SYS OBJECT

_sys_vm = new Jnaric();

_sys_vm.name = "sys";
_sys_vm.TypeURI = "~/sys/ramstore";
_sys_vm.SecurityURI = "~/sys/anarchic"; // no IPC for terminal at all
_sys_vm.parent = _terminal_vm; // the server root?? username?? FUCK!!! XXX TODO !!!!!!!!!!!!
                          // the parent should be our username - REATTACH PARENT when authenticated!!
_sys_vm.uri = _sys_vm.parent.uri + "/"+_sys_vm.name; // rewrite THIS when authenticated...!!
                          // WARNING!!! XXX TODO will get the wrong URI when authenticated!!
_sys_vm.serID = -1; // can never be serialized
_sys_vm.childList = {}; 

_sys_vm.global.initIPCLock = true; // THIS to be flushed by security validateRequest method init
_sys_vm.global.wakeupIPCLock = true; // THIS to be flushed by a call to setSecurityState method

// BINDING part
_sys_vm.bind_dom(); // XXX not ever bind DOM???
_sys_vm.bind_om(); // bind the protected EOS object model

// TWEAKINIT part

_sys_vm.load("anarchic.jn");
_sys_vm.load("ramstore.jn");


// register it
_terminal_vm.childList["sys"] = _sys_vm;
__eos_objects["~/sys"] = _sys_vm;

_cn = 0;

ffoo = function () { 
    _cn++; 
    if(_cn == 4) {
        _terminal_vm.load("terminal.jn"); 
        hubConnection.connect();
    }
}; // XXX run terminal when 4 objects initialized!

_sys_vm.onfinish = function () {
    _sys_vm.onfinish = ffoo;
    _sys_vm.evaluate("wakeupIPCLock=false;"); 
}; 


function manualRamstoreObject(oname, oparent) {
    var _vm = new Jnaric();

    _vm.name = oname;
    _vm.TypeURI = "~/sys/ramstore";
    _vm.SecurityURI = "~/sys/anarchic"; // no IPC for terminal at all
    _vm.parent = oparent; // the server root?? username?? FUCK!!! XXX TODO !!!!!!!!!!!!
                              // the parent should be our username - REATTACH PARENT when authenticated!!
    _vm.uri = _vm.parent.uri + "/"+oname; // rewrite THIS when authenticated...!!
                              // WARNING!!! XXX TODO will get the wrong URI when authenticated!!
    _vm.serID = -1; // can never be serialized
    _vm.childList = {}; 

    _vm.global.initIPCLock = true; // this will be normally unset
    _vm.global.wakeupIPCLock = true; // this will emulate like we're deserializing and will lock IPC until we explicitly unlock

    // BINDING part
    _vm.bind_dom(); // XXX not ever bind DOM???
    _vm.bind_om(); // bind the protected EOS object model

    // TWEAKINIT part

    _vm.load("anarchic.jn");
    _vm.load("ramstore.jn");
        
    oparent.childList[oname] = _vm;
    __eos_objects[_vm.uri] = _vm;
    return _vm;

}

// NOW CREATE anarchic OBJECT



_anarchic_vm = manualRamstoreObject("anarchic", _sys_vm);
_anarchic_vm.onfinish = function () {
    _anarchic_vm.onfinish = ffoo;
    _anarchic_vm.evaluate("sdata = fetchUrl('anarchic.jn');wakeupIPCLock=false;"); 
}; // WARNING!? XXX precedence test heeded here!!!!!!

// NOW CREATE ramstore OBJECT
_ramstore_vm = manualRamstoreObject("ramstore", _sys_vm);
_ramstore_vm.onfinish = function () { 
    _ramstore_vm.onfinish = ffoo;
    _ramstore_vm.evaluate("sdata = fetchUrl('ramstore.jn');wakeupIPCLock=false;"); 
}; // WARNING!? XXX precedence test heeded here!!!!!!

// create ic.jn object
_ic_vm = manualRamstoreObject("ic", _sys_vm);
_ic_vm.onfinish = function () {
    _ic_vm.onfinish = ffoo;
    _ic_vm.evaluate("sdata = fetchUrl('ic.jn');wakeupIPCLock=false;"); 
}; 




///////////////////////////////////////////////////////
///////////////////////////////////////////////////////////////////////////////////


function randomString( string_length ) {
	var chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXTZabcdefghiklmnopqrstuvwxyz";
	var randomstring = '';
	for (var i=0; i<string_length; i++) {
		var rnum = Math.floor(Math.random() * chars.length);
		randomstring += chars.substring(rnum,rnum+1);
	}
	return randomstring;
}

// TODO: parse kernel parameters, use terminal_id and terminal_key as logon credentials
(function () {
var params = location.href.toString().split('#')[1];
var nv;
if(params) {
    var lp = params.split(",");
    for(var i=0; i<lp.length; i++) {
        if(lp[i].search("=") > -1) {
            nv = lp[i].split("=");
            KCONFIG[nv[0]] = nv[1];
        }
    }
}
})()

// do announce with new credentials if the hubConnectionChanged hook is received
//       this is rather a terminal issue!
hubConnection = {
    receive: null, // to be set by jsobject
    fresh: true,
    ___SESSIONKEY: randomString(KEY_LENGTH),
    stomp: new STOMPClient(),
    rqe: {},
    acks: {},
    announce: function () {
        // TODO: announce ourself with credentials so server says we're the one we need
        //       i.e. send terminal authentication data
        // do announce only when connected!
        if(window.console) console.log("announcing...");
        var ann = { "session": this.___SESSIONKEY };
        if(KCONFIG.terminal_id && KCONFIG.terminal_key) { // TODO document this!
            ann.terminal_id = KCONFIG.terminal_id;
            ann.terminal_key = KCONFIG.terminal_key;
        }
        this.stomp.send(JSON.stringify(ann), ANNOUNCE_PATH); // we will receive our terminal_id back!
    },
    
    init: function () {
    
        this.stomp.onopen = function() {
        };

        this.stomp.onclose = function(c) { 
            // TODO: notify terminal of events
            setTimeout( (function () { hubConnection.connect(); }), 2000);
            if(window.console) console.log('Lost Connection, Code: ' + c); // TODO: log to terminal?
        };

        this.stomp.onerror = function(error) {
            if(window.console) console.log("Error: " + error);
        };

        this.stomp.onerrorframe = function(frame) {
            if(window.console) console.log("Errorframe: " + frame.body);
        };

        this.stomp.onconnectedframe = function() {
            // TODO: notify terminal of events
            if(hubConnection.fresh) {
                
                hubConnection.fresh = false;
                hubConnection.announce(); // XXX we dont need to announce each time we reconnect. This should be a transparent process
            }
            
            var hr = function () {
                hubConnection.send_real();
            };
            
            hubConnection.stomp.subscribe(hubConnection.___SESSIONKEY);
            
            clearInterval(hubConnection.si);
            hubConnection.si = setInterval(hr, RQ_RESEND_INTERVAL); 
            
        };
        
        var self = this;

        this.stomp.onmessageframe = function(frame) {
            // here to receive the messages. 
            // take care of 'session lost' errors!
            /*
            // in fact, headers do not work in Orbited in this configureation 
            if(frame.headers.error && frame.headers.error == "NOSESSION") {
                hubConnection.announce();
                return;
            }
            */
            // now receive ack
            /*
            if(frame.headers.ack) {
                self.ack_rcv(frame.headers.ack);
                return;
            }
            */
                        
            // now decode body
            try {
                var rq = JSON.parse(frame.body);
            } catch (e) {
                if(window.console) console.log("Invalid JSON data received: "+frame.body);
                return;
            }
            
            if(rq.ack) {
                self.ack_rcv(rq.ack);
                return;
            }
            
            if(rq.error && rq.error == "NOSESSION") {
                if(window.console) console.log("no session, doing announce");
                hubConnection.announce();
                return;           
            }

            // send ack that we've received the stuff
            if(! self.ack_snd(rq.id)) return; // means we've already processed

            // now pass further
            self.receive(rq);
            
            if(window.console) console.log(frame.body)
        };

    },
    
    connect: function () {
        if(window.console) console.log("starting HUB connection...");
        this.stomp.connect(E_SERVER, E_PORT, "eos", "eos"); 
    },
    
    send: function (rq) {
        this.rqe[rq.id] = {r: rq, t: (new Date()).getTime()};
        this.send_real();
    },
    
    send_real: function () {
        var ct = (new Date()).getTime();
        for(var i in this.rqe) {
            if(i == "__defineProperty__") continue; // XXX FUCK!!
            if(ct - this.rqe[i]["t"] > ACK_TIMEOUT) {
                // XXX only for requests??
                
                if ("response" in this.rqe[i]["r"]) {
                    // do nothing??? we just failed to send resp
                    // TODO: decide on what to do if we cannot send responses!!
                    // TODO: log something!
                } else { // request failed
                    // notify silently
                    this.rqe[i]["r"]["status"] = "ECONN"; // DOC document this too
                    this.rqe[i]["r"]["result"] = "Too much resend to HUB fails. Giving up."; // DOC document this too
                    this.receive(this.rqe[i]["r"]);
                }

                delete this.rqe[i];
                
            } else {
                this.rqe[i]["r"].session = this.___SESSIONKEY;
                this.stomp.send(JSON.stringify(this.rqe[i]["r"]), HUB_PATH);
            }
        }
        // cleanup ACKs window
        
        for(var i in this.acks) {
            if(i == "__defineProperty__") continue; // XXX FUCK!!
            if(ct - this.acks[i] > MAX_WINDOW_SIZE) {
                delete this.acks[i];
            }
        }
    },
    
    ack_rcv: function (rqid) {
        if(window.console) console.log("ack!");
        delete this.rqe[rqid];
    },
    
    ack_snd: function (rqid) {
        var t = true;
        if(rqid in this.acks) t = false;
        this.acks[rqid] = (new Date()).getTime(); // XXX make sure the local rqID and response (HUB ones) namespaces never get intersected
        if(window.console) console.log("sending ack");
        this.stomp.send(JSON.stringify({ack: rqid}), HUB_PATH, {ack: rqid});
        return t;
    },
    
    abort: function (rqid){
        delete this.rqe[rqid];
    }
};

// start the pinger
setTimeout((function() {hubConnection.send({id: __jn_stacks.newId(), uri: "/", method: "ping", args: []});}), 90000)

hubConnection.init();
hubConnection.receive = eos_rcvEvent; // XXX this interconnects with jsobject.js in an ugly way...




