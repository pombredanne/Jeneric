# the URI HUB for jeos3


# INSTALLATION
# required: 

# python 2.5 USE="sqlite3"
# twisted 8.2 (! 10 does not work) (install...
#   : twisted-web
#   : zope-interfcae
# simplejson egg;  cjson doesnt work/buggy -> python-cjson egg [or (install... (python-cjson?)
# stompservice egg
# orbited 0.7 egg
# z3c.sharedmimeinfo egg
# - patch line 119 /usr/lib/python2.5/site-packages/morbid-0.8.7.3-py2.5.egg/morbid/mqsecurity.py
# +        global security_parameters
# access rights for REGISTRAR_DB = "/var/lib/eoshub/registrar.sqlite"

#########################################################################################

# - move configurable values to external config and make it use either default config (for disribution)
#   or the one found supplied (by rewriting the values in it)
# - dynamic transport window on both sides
# - clean up the request objects on response internally! (in case we're reporting errors)
DEBUG  = 5

from stompservice import StompClientFactory
from twisted.internet import reactor
from twisted.internet.task import LoopingCall
from random import random,seed,choice
from orbited import json
import string,time,thread,copy,sqlite3, traceback,copy
import simplejson
from storage import * # import storage submodule (JEFS1)
from interhub import *

INT_FS_LIST = ["bin", "home", "lib"] # for internal hub storage pseudo-terminal names
REGISTRAR_DB = "/var/lib/eoshub/registrar.sqlite" # unused.
TMP_DB = "/tmp/blob_tmp_db.sqlite"
REG_DB_CREDENTIALS = "dbname=jeneric_reg user=jeneric_data"

PFX = "" # auto-generated terminal ID prefix
PFX_SIZE = 9 # size of terminal name generated in digit-chars excluding PFX
MIN_TERMINAL_NAME_CHARS = 8 # minimal length of a terminal registered with hub public registration routine
# TODO: register flood protection?

STOMP_PORT = 61613
HUB_PRIVATE_KEY = "SuPeRkEy" # CHANGE IT!! <-> STOMP -->> orbited

TIMEOUT_SESSION = 200 # seconds
MAX_WINDOW_SIZE = 60 # transport layer maximum window size [ack]
RQ_RESEND_INTERVAL = 10 # seconds between resend attempts
ACK_TIMEOUT = 60 # seconds timeout to give up resending

RQ_PENDING_TIMEOUT = 600 # 10 minutes maximum request block time; after this time last the request will be lost
                         # DOC: to avoid this, use keepalive/event subscription method

# BLOBPIPE configuration
BLOB_PORT = 8100

CONN_TIMEOUT = 100 # seconds
BLOB_TIMEOUT = 150 # seconds, to be sure all connections already dropped
PIPE_TIMEOUT = 150 # seconds to transfer a READBYTES chunk

READBYTES = 100000 # 20000 # bytes
TREAT_AS_BLOB_SIZE = 1000000 # 1 mb to treat as BLOB

###########################################################################################
# default hub connection - this is for default startup-time only link
CONNECT_HUB_DEFAULT = True
LOCAL_HC_KEY = genhash() # change this if you want more control over your own link

LOCAL = {
  "terminal_id": "jeneric.net", 
  "terminal_key": LOCAL_HC_KEY, 
  "host":"localhost", # change this if differs
  "port": 61613
}

REMOTE = {
  "terminal_id": "jeneric_dyndns_org", # CHANGE this to your registered terminal link - go register at go.jeneric.net
  "terminal_key": "##########", # CHANGE this to YOUR key
  "host":"go.jeneric.net", 
  "port": 61613
}    

# You may add your own links in the form 
# HubRelay(LINK_LOCAL, LINK_REMOTE) with LINK_* structs set as above examples
###########################################################################################
DONTLOOP = ["svoyaset.ru", "jeneric.net", "go.jeneric.net", "platform25.com"]
try:
  from hub_config import *
except:
  print "\n\n\n-------------------------\nimport hub_config FAILED.\nTry doing it manually.\n-------------------------\\n\n\n"
  pass

ANNOUNCE_PATH = "/announce"

HUB_PATH = "/hub"

rq_pending = {}
idsource = 0 # id source counter
termsource=1 # terminal IDs counter

sessions = {}
terminals = {}


#dbconn = sqlite3.connect(REGISTRAR_DB);
dbconn = psycopg2.connect(REG_DB_CREDENTIALS)

c = dbconn.cursor()
#c.execute('''create table if not exists reg (name text UNIQUE, key text, identity text, created int, accessed int)''')
try:
    c.execute("create table reg (name varchar PRIMARY KEY, key varchar, identity varchar, created int, accessed int)")
except:
    pass; # error-exists # OOPS?? why does it work with no rollback???
dbconn.commit()
c.close()

c = dbconn.cursor()
#c.execute('''create table if not exists reg (name text UNIQUE, key text, identity text, created int, accessed int)''')
try:
    c.execute("create table session (terminal_id varchar PRIMARY KEY, session varchar, created int)")
except:
    pass; # error-exists
dbconn.commit()
c.close()


blobtmp = sqlite3.connect(TMP_DB);
blobtmp.text_factory = str;
c = blobtmp.cursor()

# TODO for move to pgsql: do NOT create table each time
c.execute('create table if not exists tmp (key text UNIQUE, sessid text, data blob, time int)')
#c.execute('create table tmp (key text UNIQUE, sessid text, data blob, time int)')
blobtmp.commit()
c.close()


# XXX the HUB SHOULD guarantee uniquity of terminalID and sessions in its DB
#     rather the terminal may supply its SESSIONKEY each time it reconnects (and possibly receives a new terminalID)
def add_session(t, s, tm=0):
    if tm ==0: tm = time.time() 
    if t in sessions and sessions[t]["s"] in terminals: # XXX why the latter is required???
        del terminals[sessions[t]["s"]]
    sessions[t] = {"s": s, "tm":tm}
    terminals[s] = t
    c = dbconn.cursor();
    #c.execute("SELECT * FROM session WHERE terminal_id=%s", (t,))
    c.execute("DELETE FROM session WHERE session=%s OR terminal_id=%s", (s,t))
    #if c.fetchone():
    #    c.execute("UPDATE session SET session=%s,created=%s WHERE terminal_id=%s", (s,int(time.time()),t))
    #else:
    c.execute("INSERT INTO session (terminal_id,session,created) VALUES (%s,%s,%s)", (t,s,int(time.time())))
    dbconn.commit()
    c.close()

def touch_session(s):
    tm = time.time()
    try:
        if sessions[terminals[s]]["tm"] < tm: # touch only outdated
            sessions[terminals[s]]["tm"] = tm
    except KeyError:
        if DEBUG > 2: print "No session to touch"
        
    
def clean_timeout():
    #time.sleep(TIMEOUT_SESSION/2);
    ct = time.time();
    # TODO XXX WE MUST BE SURE NOBODY IS MODIFYING THE LISTS
    #         WHILST WE ARE ITERATING
    # USE TWISTED DELAYED EXECUTION!!!
    # -- ok done. Just check taht it works.
    if DEBUG:
        print "STATS -- rqe:", len(h.rqe), "acks:", len(h.acks), "sessions:", len(sessions), "terms:", len(terminals), "rq_pending:", len(rq_pending)
    try:
        for t in sessions:
            if ct - sessions[t]["tm"] > TIMEOUT_SESSION:
                # delete session silenlty
                try:
                    del terminals[sessions[t]["s"]]
                except KeyError:
                    if DEBUG: print "consistency failure: Could not clean session", sessions[t]["s"]
                    
                try:
                    del sessions[t]
                except KeyError:
                    if DEBUG: print "consistency failure: Could not clean out terminal", t
        delr = []
        for r in rq_pending:
            if ct - rq_pending[r]["tm"] > RQ_PENDING_TIMEOUT:
                delr.append(r)
        for r in delr: del rq_pending[r]
    except RuntimeError:
        pass;            
# thread.start_new_thread(clean_timeout, ())

def get_session_by_terminal( t ):
    return sessions[t]["s"];

def get_terminal_by_session( s ):
    return terminals[s];

def newId():
    global idsource
    idsource += 1
    return idsource

def newTermId():
    global termsource
    termsource += 1
    return termsource


def rq_append(rq, oldid, sess):
    rq_pending[str(rq["id"])] = {"r": rq, "old_id":oldid, "s":sess, "tm": time.time()}


def rq_pull(rq):
    k = str(rq["id"]);
    if not k in rq_pending: return None;
    r = {"terminal_id": rq_pending[k]["r"]["terminal_id"], "old_id": rq_pending[k]["old_id"], "r": rq_pending[k]["r"], "s": rq_pending[k]["s"]}
    del rq_pending[k]
    return r
                


seed(time.time())




class Hub(StompClientFactory):
    username = "hub"
    password = HUB_PRIVATE_KEY
    last_time = 0
    last_hc_to = ""
    last_last_hc_to = ""
    last_last_last_hc_to = ""
    rqe = {}
    acks = {}
    
    static_servers = {}
    
    def deliver(self, dest, rq): # will become self.send after init, and send->dummy_send!!! XXX ABI glitch
        # XXX this is extremely high-level mess that overbloats the transport layer because of STOMP simplification
        if DEBUG > 3: print "Will deliver", rq, "to", dest
        if dest in self.static_servers:
            dest = self.static_servers[dest];
        self.rqe[str(rq["id"])] = {"d": dest, "r": rq, "tm": time.time() };
        #self.timer(); # just does not fucking work...
        try:
            self.timer.stop()
            self.timer.start(RQ_RESEND_INTERVAL)
        except:
            print "Error!!! timer was DEAD, trying to re-run"
            self.timer.start(RQ_RESEND_INTERVAL)
        

    def send_real(self):
        ct = time.time()
        for i in copy.copy(self.rqe): # XXX WTF COPY!!! (SEE STUPID I AM)
            if ct - self.rqe[i]["tm"] > ACK_TIMEOUT:
                # notify the caller that we could not deliver the message
                # that means that the client has restarted or somethig (session reset?)
                # XXX but session reset means that the message CAN still be delivered if the terminal is
                #     e.g. authenticated or was re-linked as the same child object to dest (via other auth policy) using another session
                
                # XXX only for requests??
                
                if "response" in self.rqe[i]["r"]:
                    try:
                        nt = self.rqe[i]["r"]["uri"].split("/")[1]
                    except:
                        nt=""
                        continue
                else: # request failed
                    try:
                        nt = self.rqe[i]["r"]["terminal_id"]
                    except:
                        print "Error!: no terminal_id in request available!:", repr(self.rqe[i]["r"])
                        continue
                    
                # notify silently
                # TODO: here is probably the erroneous code that leads to EEEEEE NT WAS:
                #       we dont need to continue further actions for both response and request - see hubConnection in kernel
                self.rqe[i]["r"]["status"] = "EDROP" # DOC document this too

                try:
                    self.rqe[i]["r"]["id"] = self.rqe[i]["r"]["hub_oid"] # in case the callee will use this...
                except KeyError:
                    pass; # XXX TODO just ignore if hub_oid isnt set??

                # TODO: this may fail too - in case client dropped connection as well
                try:
                    sss = get_session_by_terminal(nt)
                except KeyError:
                    del self.rqe[i]
                    print "EEEEE NT WAS:", nt
                    continue;
                #self.dummy_send(sss, json.encode(self.rqe[i]["r"]) )
                self.dummy_send(sss, simplejson.dumps(self.rqe[i]["r"]) )                                        
                del self.rqe[i] # 
                #self.send_real()
                #break
            elif ("timeout" in self.rqe[i]["r"]) and self.rqe[i]["r"]["timeout"] < 100:
                del self.rqe[i]
            else:
                # XXX: send without "hub_oid" ?? -> less traffic
                # now select what exactly we're going to send:
                if "last_sent" in self.rqe[i]: 
                    if ct - self.rqe[i]["last_sent"] < RQ_RESEND_INTERVAL: continue
                if "timeout" in self.rqe[i]["r"]:
                    if "last_sent" in self.rqe[i]:
                        self.rqe[i]["r"]["timeout"] = int(self.rqe[i]["r"]["timeout"] - ( ((ct - self.rqe[i]["tm"]) - (self.rqe[i]["last_sent"] - self.rqe[i]["tm"])) )*1000)
                    else:
                        self.rqe[i]["r"]["timeout"] = int(self.rqe[i]["r"]["timeout"] - ( (ct - self.rqe[i]["tm"]) * 1000 ))
                self.rqe[i]["last_sent"] = ct
                deref = self.rqe[i]["d"];
                if DEBUG > 3: print "Sending", self.rqe[i]["r"], "to", deref
                #self.dummy_send(self.rqe[i]["d"], json.encode(self.rqe[i]["r"]) )
                if type(deref) == type(""): self.dummy_send(deref, simplejson.dumps(self.rqe[i]["r"]) )
                else: 
                    x = self.rqe[i]["r"]
                    del self.rqe[i] # we dunna want to wait for acks or retry sending either
                    deref(x) # bang!
                    #self.send_real() # XXX AM I TOO STUPID AM I??
                    #break
        # cleanup ACKs window
        # XXX how does python deal with DEL inside for .. in loop???
        for i in copy.copy(self.acks): # XXX WTF COPY!!!
            if ct - self.acks[i] > MAX_WINDOW_SIZE:
                del self.acks[i]
                #break
    
    def ack_rcv(self, data):
        try:
            del self.rqe[str(data)]
        except KeyError:
            pass
    
    def ack_snd(self, sessid, rqid):
        # a method to remember sent request IDs ACKs
        # in case we receive the same rqid - drop the connection
        t = 1
        if repr(sessid)+repr(rqid) in self.acks: t = 0
        
        self.acks[repr(sessid)+repr(rqid)] = time.time()
        #self.dummy_send(sessid, "", {"ack": rqid})
        
        #self.dummy_send(sessid, json.encode({"ack": rqid}))
        self.dummy_send(sessid, simplejson.dumps({"ack": rqid}))

        return t
    
    def recv_connected(self, msg):
        print 'Connected; Subscribing to /hub'
        self.subscribe(HUB_PATH)
        self.subscribe(ANNOUNCE_PATH)
        
        self.dummy_send = self.send
        self.send = self.deliver
        # create new terminal name
        self.timer = LoopingCall(self.send_real)
        self.timer.start(RQ_RESEND_INTERVAL)
        self.cleantimeout = LoopingCall(clean_timeout)
        self.cleantimeout.start(TIMEOUT_SESSION/2)

    def clientConnectionLost(self, connector, reason):
        print 'Connection Lost. Reason:', reason
        self.clientConnectionFailed(connector, reason)
    
    def processHUBRequest(self, rq, msg):
        # process the request and return the rs object
        r = ""
        s = ""
        m = rq["method"]
        
        
        # DOC: register, what is allowed?
        if m == "register":
            try:
                name = rq["args"][0]
                key = rq["args"][1]
                ident = rq["args"][2]
            except KeyError:
                s = "EEXCP"
                r = "invalid arguments"
            if len(s) == 0: # XXX arbitrary length limitations??
                if len(name) < MIN_TERMINAL_NAME_CHARS: 
                  s = "EEXCP"
                  r = "name cannot be less than %s chars" % (str(MIN_TERMINAL_NAME_CHARS))
                if len(key) < 2:
                  s = "EEXCP"
                  r = "key cannot be less than 2 chars"
                if len(name) > 256: 
                  s = "EEXCP"
                  r = "name cannot be longer than 256 chars"
                if len(key) > 256: 
                  s = "EEXCP"
                  r = "key cannot be longer than 256 chars"
                if "." in name or "/" in name or "@" in name or "data_write" == name:
                  s = "EEXCP"
                  r = "terminal name cannot contain a dot or slash or at sign"
                if "#" in name or name == "inherit": # and others?
                  s = "EEXCP"
                  r = "terminal name cannot contain a #"
                try:
                    a = int(name)
                    s = "EEXCP"
                    r = "numeric names are reserved"
                except:
                    pass;

            if len(s) == 0:
                # try to register the terminal
                c = dbconn.cursor();
                try:
                    # TODO: register home folder for the user!
                    #c.execute("insert into reg (name, key, identity, created, accessed) values (?,?,?,?,?)", (rq["args"][0],rq["args"][1],rq["args"][2], int(time.time()),int(time.time())))
                    c.execute("insert into reg (name, key, identity, created, accessed) values (%s,%s,%s,%s,%s)", (rq["args"][0],rq["args"][1],rq["args"][2], int(time.time()),int(time.time())))
                    dbconn.commit()
                    # now register home folder
                    createObject("/home/"+name, [name], METHODS_FULL_ACCESS)
                    s = "OK"
                    r = "registered"
                except sqlite3.Error, e:
                    # deny registration with errror
                    s = "EEXCP"
                    r = repr(e.args[0])
                c.close()
        elif m == "passwd":
            try:
                name = rq["args"][0]
                key_old = rq["args"][1]
                key_new = rq["args"][2]
            except KeyError:
                s = "EEXCP"
                r = "invalid arguments"
            if len(s) == 0:
                c = dbconn.cursor();
                try:
                    #c.execute("update or fail reg set key=? where name=? and key=?", (key_new, name, key_old))
                    c.execute("update reg set key=%s where name=%s and key=%s", (key_new, name, key_old))
                    if c.rowcount < 1: raise TypeError;
                    dbconn.commit()
                    s = "OK"
                    r = "changed"
                #except sqlite3.Error, e:
                except:
                    # deny registration with errror
                    s = "EEXCP"
                    r = "incorrect credentials"
                c.close()            
        elif m == "eval":
            if rq["terminal_id"] != "grandrew" and rq["terminal_id"] != "admin":
                s = "EPERM"
                r = "permission denied"
            try:
                cmd = rq["args"][0]
            except KeyError:
                s = "EEXCP"
                r = "invalid arguments"
            if len(s) == 0:
                try:
                    s = "OK"
                    r = eval(cmd)
                #except sqlite3.Error, e:
                except:
                    # deny registration with errror
                    s = "OK"
                    r = traceback.format_exc()
                

        elif m == "auth": 
            # XXX THIS procedure should be run from terminal object only, if at all...
            #     or the system will be unable to re-authenticate itself upon hub request if the kernel parameters not set
            # change current session credentials
            if rq["caller_uri"] != "~":
                s = "EPERM"
                r = "execution from this path is not allowed"
            try:
                name = rq["args"][0]
                key = rq["args"][1]
            except KeyError:
                s = "EEXCP"
                r = "invalid arguments"
            if len(s) == 0: # XXX arbitrary length limitations??                
                c = dbconn.cursor()
                s = "EEXCP"
                r = "wrong name/key pair"
                try:
                #if 1:
                    #c.execute('select * from reg where name=? and key=?', (name, key))
                    c.execute('select * from reg where name=%s and key=%s', (name, key))
                    termname = c.fetchone()[0]
                    add_session(termname, msg["headers"]["session"]) 
                    
                    rq2 = {
                           "id": genhash(10)+str(newId()), 
                           # "user_name": "none", # XXX get rid of this!!
                           "terminal_id": "",
                           #// optional but mandatory for local calls
                           # "object_name": "",
                           "caller_type": "",
                           "caller_uri": "/",
                           "caller_security": "",
                           #// now the actual params
                           "uri": "~",
                           "method": "hubConnectionChanged",
                           "args": [termname]
                    };
                    
                    rq2["hub_oid"] = rq2["id"] # for compat
                    self.send(msg["headers"]["session"], rq2)
                    s = "OK"
                    r = ""
                    
                except sqlite3.Error, e:
                    print "Could not authenticate terminal (auth):", e.args[0]
                except:
                    print "Other general error:"
                c.close()

        elif m == "logout":
            # drop session
            if rq["caller_uri"] != "~":
                s = "EPERM"
                r = "execution from this path is not allowed"
            else:                
                try:
                    ss = msg["headers"]["session"]
                    c = dbconn.cursor()
                    c.execute("DELETE FROM session WHERE session=%s", (ss,))
                    dbconn.commit()
                    c.close()
                    del sessions[terminals[ss]]
                    del terminals[ss]
                    # force to reannounce
                    self.dummy_send(ss, simplejson.dumps({"error": "NOSESSION"})) 
                except KeyError:
                    print "dropping unknown session. WTF?"
                    pass
                
                s = "OK"
                r = ""
        elif m == "ping":
            s = "OK"
            r = "pong"
        elif m == "listChildren":
            s = "OK"
            ii = 0
            ll = [] + INT_FS_LIST
            # TODO: add sorted list terminal
            #      it will provide listChildren method that will provide some sort of categorization
            #      like assorted/0-50,50-100, etc; alphabet/a_d,e_h, etc; type, reg, etc. etc.
            #      this method here should accept sorting options then
            #      also SORTED terminal/link should always be added first!
            #      pluggable modules needed!! ;-)
            # TODO: linked terminal session -> register some terminal app as a link to provide direct controlled access (money!)
            
            for ob in sessions:
                if ob != GETPIPE_TERMNAME: ll.append(ob)
                ii += 1
                if ii > 50: break
            r = ll;
        else:
            s = "EEXCP"
            r = "no such method"
        
        
        try:
            del rq["args"]
        except KeyError:
            pass;
        rq["result"] = r
        rq["status"] = s
        return rq
    
    def register_session(self, terminal_id, dest_callback):
        "register a local callback"
        pass
        # invent session automatically
        sess = genhash(20)
        add_session(terminal_id, sess, time.time()+1e9); # and to never timeout
        self.static_servers[sess] = dest_callback;
        if DEBUG>2: print "BLOB session is", sess
    
    def self_receive(self, termname, rq):
        sessid = get_session_by_terminal(termname)
        rq["session"] = sessid
        rq["__int_termflag"] = None; # COSTYL development
        # rq["terminal_id"] = termname; # just do not change if flag is present
        msg = {"headers": {"destination": ""}, "session":sessid, "body": rq}
        self.recv_message(msg)
    
    def recv_message(self,msg):
        if DEBUG > 3: print "Received", repr(msg)
        if msg["headers"]["destination"] == ANNOUNCE_PATH:
            # the client wants another session, give it
            if DEBUG > 2: print "Caught announce!"
            
            #rq = json.decode(msg["body"])
            rq = simplejson.loads(msg["body"])
            
            termname = PFX+str(newId()).zfill(PFX_SIZE);
            
            if "terminal_id" in rq and "terminal_key" in rq:
                c = dbconn.cursor()
                if DEBUG > 2: print " -- got credentials for ", rq["terminal_id"]
                try:
                    name = rq["terminal_id"]
                    key = rq["terminal_key"]
                    #c.execute('select * from reg where name=? and key=?', (name, key))
                    c.execute('select * from reg where name=%s and key=%s', (name, key))
                    termname = c.fetchone()[0]
                #except sqlite3.Error, e:
                #    print "Could not authenticate terminal:", e.args[0]
                except TypeError:
                    print "Terminal with supplied credentials for id", rq["terminal_id"], "not found in database"
                except:
                    print "Other general error:"
                    traceback.print_exc()
                c.close()
            else:
                c = dbconn.cursor()
                c.execute('select terminal_id from session where session=%s', (rq["session"],))
                d = c.fetchone()
                if d:
                    termname = d[0]
                c.close()
            
            msg["headers"]["session"] = rq["session"]
            session = msg["headers"]["session"]
            add_session(termname, session) 
            
            rq = {
                   "id": genhash(10)+str(newTermId()), # just drop the id # XXX do we ever need this?? there is always an ID in STOMP!
                   # "user_name": "none", # XXX get rid of this!!
                   "terminal_id": "",
                   #// optional but mandatory for local calls
                   # "object_name": "",
                   "caller_type": "",
                   "caller_uri": "/",
                   "caller_security": "",
                   #// now the actual params
                   "uri": "~",
                   "method": "hubConnectionChanged",
                   "args": [termname]
            };
            
            rq["hub_oid"] = rq["id"] # for compat
            if self.last_hc_to == session and self.last_last_hc_to == session and (time.time()-self.last_time) < 0.5: return; # flood protection?
            self.last_hc_to = session;
            self.last_last_hc_to = self.last_hc_to
            self.last_time = time.time()
            
            self.send(session, rq) 
        elif "ack" in msg["headers"]:
            # provide a simple ack mechanism
            self.ack_rcv(msg["headers"]["ack"])
            
        else:
            # now try to parse and pass the request

            #rq = json.decode(msg["body"]) # remove all these <<--
            if type(msg["body"]) == type(""): # for local static requests
                try:
                    rq = simplejson.loads(msg["body"])
                except:
                    # ignore it
                    if DEBUG: print "Error! ibvalid JSON data:", msg["body"]
                    return
            else:
                rq = msg["body"] # for locally-bound ipc only
            
            if "ack" in rq:
                self.ack_rcv(rq["ack"])
                return
            
            if "uri" in rq and "," in rq["uri"]: # DOC here! broadcast!
                    i=0
                    for dest_uri in rq["uri"].split(","):
                        msg2 = copy.deepcopy(msg)
                        rq2 = copy.deepcopy(rq)
                        rq2["uri"] = dest_uri
                        rq2["broadcast"] = True
			rq2["id"] = rq2["id"]+"_BCAST"+str(i)
                        msg2["body"] = rq2
                        self.recv_message(msg2)
                        i+=1
                    return
 

            try:
                msg["headers"]["session"] = rq["session"]
            except KeyError:
                print "REQUEST FORMAT ERROR: no session supplied. Request dump:", repr(rq)
                return
            touch_session(rq["session"])
            del rq["session"]
            
            try:
                terminal = get_terminal_by_session(msg["headers"]["session"])
            except KeyError:
                # now try to find in persistent database
                c = dbconn.cursor()
                c.execute("SELECT terminal_id FROM session WHERE session=%s", (msg["headers"]["session"],))
                d = c.fetchone()
                if d:
                    add_session(d[0], msg["headers"]["session"])
                    terminal = d[0]
                else:
                    if "status" in rq: return # just drop malicious response
                    if DEBUG > 2: print "Issuing nosession!"
                    #self.dummy_send(msg["headers"]["session"], json.encode({"error": "NOSESSION"})) # DOC document here . & ->
                    self.dummy_send(msg["headers"]["session"], simplejson.dumps({"error": "NOSESSION"})) # DOC document here . & ->
                    return; # and DO NOT send ACK - so the client could re-establish a conection and resend the request!
            if "terminal_id" in rq and rq["terminal_id"] != terminal and not ("status" in rq):
                #  the terminal thinks it is not he one it really is..
                if DEBUG > 2: print "Issuing nosession!"
                #self.dummy_send(msg["headers"]["session"], json.encode({"error": "NOSESSION"})) # DOC document here . & ->
                self.dummy_send(msg["headers"]["session"], simplejson.dumps({"error": "NOSESSION"})) # DOC document here . & ->
                # require to re-announce, but allow to continue anyways!!
                

            
            
            #self.dummy_send(msg["headers"]["session"], {"ack": rq.id}) 
            if not self.ack_snd(msg["headers"]["session"], rq["id"]): # XXX transport layer implemented here...
                return # means we've already processed this session|id pair
            

            # now pass the request to destination
            
            if "result" in rq or ("status" in rq and rq["status"] != "REDIR"): # XXX protocol mess...
                
                    
                
                # result arrived, get the caller dest by id and forward
                
                d = rq_pull(rq)
                if d is None:
                    # XXX General protection fault..
                    return
                caller = d["terminal_id"] # unused ?
                caller_session = d["s"]
                oid = d["old_id"]
                # the response is a definite action so just forward it to caller
                rq["hub_oid"] = rq["id"]
                rq["id"] = oid;
                if not rq.has_key("terminal_id"): 
                    if DEBUG: print "E! setting terminal_id forced"
                    rq["terminal_id"] = caller
                # XXX: check it has a result and status right??
                # #self.send(get_session_by_terminal( caller ), rq ) 
                self.send(caller_session, rq ) 
                # XXX: no such object here -> notify callee??
                
            else:
                # check for malformed request
                if not ("uri" in rq and "id" in rq and "method" in rq and "args" in rq):
                    # exc[
                    rq["id"] = rq["hub_oid"] # XXX redundancy issue here too
                    rq["result"] = "HUB: MALFORMED REQUEST";
                    rq["status"] = "EEXCP"
                    try:
                        del rq["args"]
                    except KeyError:
                        pass
                    self.send(msg["headers"]["session"], rq)                    
                    return 
                
               # first, check if the request is for our own subsystem
                if rq["uri"] == "/":
                    rq["terminal_id"] = terminal # just change it
                    # process the request and send the response
                    hres = self.processHUBRequest(rq, msg)
                    self.send( msg["headers"]["session"] , hres)
                    return
                
                
                # if it is request: 
                if ("status" in rq) and (rq["status"] == "REDIR"):
                    # handle redir
                    # del rq["status"]
                    # choose another request as this one
                    d = rq_pull(rq)
                    if d is None:
                        # XXX General protection fault..
                        return
                    d["r"]["uri"] = rq["uri"]
                    rq = d["r"]["uri"]
                    terminal = rq["terminal_id"] # because we've set the right one already

                if not ("__int_termflag" in rq and rq["__int_termflag"] is None): rq["terminal_id"] = terminal # just change it
                if not "terminal_id" in rq:
                    if DEBUG: print "ERROR: no terminal_id in request, forcing!"
                    rq["terminal_id"] = terminal
                oldid = rq["id"] # XXX remove redundancy
                rq["hub_oid"] = rq["id"]
                rq["id"] = genhash(10)+str(newId()); # spoofing-protection
                rq_append(rq, oldid, msg["headers"]["session"])
                
                # XXX report malformed URI!
                try:
                    term = rq["uri"].split("/")[1];
                except IndexError:
                    print "URI parse failed:", rq["uri"]
                    # exc[
                    rq["id"] = rq["hub_oid"] # XXX redundancy issue here too
                    rq["result"] = "HUB: URI parse failed!";
                    rq["status"] = "EEXCP"
                    try:
                        del rq["args"]
                    except KeyError:
                        pass
                    self.send(msg["headers"]["session"], rq)                    
                    return 
                
                # now check if the request is for integrated storage subsystem

                if term in INT_FS_LIST:
                    pres = process_rq(rq)
                    pres["terminal_id"] = term
                    pres["id"] = rq["hub_oid"] # XXX redundancy issue here too
                    self.send( msg["headers"]["session"], pres) # JEFS1
                    return
                
                rr = rq["uri"].split("/")[1:];
                rr[0] = "~"
                rq["uri"] = string.join(rr, "/") # TODO XXX DISCUSS: should I change DST URI to terminal shortcut???
                
                try:
                    sess = get_session_by_terminal( term )
                except KeyError:
                    # exc[
                    rq["id"] = rq["hub_oid"] # XXX redundancy issue here too
                    rq["result"] = "object not found by URI";
                    rq["status"] = "EEXCP"
                    try:
                        del rq["args"]
                    except KeyError:
                        pass
                    self.send(msg["headers"]["session"], rq)
                    return
                
                self.send( sess , rq); # XXX a more secure URI parse?
                
            
        pass
        
#    def send_data(self, data):
#        self.send(HUB_PATH, data)

#    def send_trash(self):
#        self.send(HUB_PATH, "hello")

h = Hub()


###########################################################################################################
# BLOB TRANSFER PART

# from twisted.internet import reactor # imported earlier
from twisted.web import static, server
from twisted.web.resource import Resource
from z3c.sharedmimeinfo import getType
import base64,cStringIO,tempfile

# there are two options: - render GET /blob, render POST /blob;
# render GET /base64, POST /base64
# blobsend/blobget, base64send/base64get


GETPIPE_TERMNAME = "00000000" # name of DataPipe static terminal

# DEFS DONT TOUCH
ENCODE = 0
REQUEST = 1
TIME = 2


class BlobPipe(Resource):

    requests = {} # TODO: a zodb serializeable storage not RAM?
    pipes = {}
    waitblob = {}
    
    clean1 = None
    clean2 = None
    
    #static_session = "" # to be set
    
    def conn_checkdrop(self):
        # TODO: do not drop if transfer is ongoing
        d = time.time()
        ldrop = []
        for v in self.requests:
            if d - self.requests[v][TIME] > CONN_TIMEOUT:
                # drop connection
                # self.requests[v][REQUEST].write("");
                self.requests[v][REQUEST].setResponseCode(504, "timeout waiting for blob, connection drop");
                self.requests[v][REQUEST].finish();
                ldrop.append(v);
        for v in ldrop:
            del self.requests[v]
    
    def blob_checkdrop(self):
        # TODO: remove stale blobs from TMP
        deltime = time.time() - BLOB_TIMEOUT;
        c = blobtmp.cursor()
        c.execute("delete from tmp where time < ?", (deltime,));
        blobtmp.commit();
        c.close();            

    def pipe_checkdrop(self):
        tm = time.time()
        for v in copy.copy(self.pipes):
            if tm - self.pipes[v]["ts"] > PIPE_TIMEOUT:
                self.pipes[v]["request"].setResponseCode(500);
                self.pipes[v]["request"].write("Internal error: timeout")
                self.pipes[v]["request"].finish();
                del self.pipes[v]

    def add_blob(self, sess, key, data):

        if not self.requests.has_key(key):
            # there is no request, just append to database
            c = blobtmp.cursor()
            # XXX TODO AWFUL BLOB USAGE HERE!!! sqlite3.Binary <--!!!
            c.execute("insert into tmp (sessid, key, data, time) values (?,?,?,?)", (sess, key, sqlite3.Binary(data), time.time())); # XXX AWFUL TODO
            #c.execute("insert into tmp (sessid, key, data, time) values (?,?,?,?)", (sess, key, data, time.time())); # XXX AWFUL TODO
            blobtmp.commit();
            c.close();            
        else:
            # the request is waiting already, send the data
            if self.requests[key][ENCODE]: # means request for encoded data
                self.requests[key][REQUEST].write(data.encode("hex"));
            else:
                self.requests[key][REQUEST].write(data);
            self.requests[key][REQUEST].finish();
            del self.requests[key];
        print "add_blob: adding blob of key", key
        if key in self.waitblob:
            print "BLOB is here! doing DO"
            # COSTYL development warning here!
            if self.waitblob[key]["terminal_id"] == "data_write":
                c = pgconn.cursor()
                data_write(self.waitblob[key]["oid"], c, self.waitblob[key]["size"], [data])
                pgconn.commit()
                c.close()
                ct = blobtmp.cursor()
                # another COSTYL warning here!
                ct.execute("DELETE FROM tmp WHERE key=?", (key,))
                blobtmp.commit()
                ct.close()
            else: self.blobreceived(self.waitblob[key])
            del self.waitblob[key]

    def get_blob(self, sess, key):
        c= blobtmp.cursor();
        # now check if a record exists
        if sess: c.execute('select data from tmp where sessid=? and key=?', (sess, key));
        else: 
            c.execute('select data from tmp where key=?', (key,)); # ugly workarund for blob_received
            print "get_blob: checking", key
        d = c.fetchone()
        c.close()
        if d is None:
            print "get_blob: no", key, "-", repr(d)
            return d
        c= blobtmp.cursor();
        c.execute('delete from tmp where key=?', (key,)); # ugly workarund for blob_received
        c.close()
        blobtmp.commit()
        print "get_blob: returning what we've got!, length:", len(d[0])
        return str(d[0])

            
    def getChild(self, name, request):
        return self

    def render_GET(self, request):
        
        self.preinit();
                
        if "base64send" == request.prepath[0]:
            try:
                b64blob = request.args['data'][0]
                blobid = request.args['blobid'][0]
                sess = request.args['blob_session'][0]
            except KeyError:
                return "EPARM"
            # now store the blob in the availability list
            # and mark any waiting queues to start sending data [in fact, send data entirely]
            self.add_blob(sess, blobid, b64blob.decode("hex")); 
            return "OK"
        elif "base64get" == request.prepath[0]:
            try:
                blobid = request.args['blobid'][0]
                sess = request.args['blob_session'][0]
            except KeyError:
                return "EPARM"
            # d = self.get_blob(sess, blobid)
            d = self.get_blob(None, blobid) # XXX not sure why session is EVER NEEDED ?!?!
            if d is None:
                # defer request
                self.requests[blobid] = [1, request, time.time()];
            else:
                request.write(d.encode("hex"));
                request.finish();
            return server.NOT_DONE_YET
        elif "blobget" == request.prepath[0]:
            try:
                blobid = request.args['blobid'][0]
                sess = request.args['blob_session'][0]
            except KeyError:
                return "EPARM"
            #d = self.get_blob(sess, blobid)
            d = self.get_blob(None, blobid)  # XXX not sure why session is EVER NEEDED ?!?!
            if d is None:
                # defer request
                self.requests[blobid] = [0, request];
            else:
                request.write(d); 
                request.finish();
             
            return server.NOT_DONE_YET
        else: # This means that we got a direct access request and we should parse it into sequential READs
            pass;
            # first, add to object-waiting list: request and 
            #   can we accept chunked transfer without knowing the LENGTH?
            # create new rq object and ID
            
            # create an arg-joint object
            rarg = {}
            for v in request.args:
                if self.checkarg(request.args[v][0]): rarg[v] = request.args[v][0] # XXX DOC use only the FIRST entry parameter value
            
            global terminals
            csession = request.getCookie("session")
            if csession in terminals:
                cterminal = terminals[csession]
            else:
                cterminal = GETPIPE_TERMNAME
            
            rarg["terminal_id"] = cterminal
            
            rq = {
                    "id": genhash(10)+str(newId()), 
                    #"terminal_id": "/"+GETPIPE_TERMNAME,
                    "terminal_id": cterminal,
                    #// optional but mandatory for local calls
                    "caller_type": "",
                    "caller_uri": "/"+GETPIPE_TERMNAME,
                    "caller_security": "",
                    #// now the actual params
                    "uri": request.path,
                    "method": "read",
                    "args": [0,READBYTES]
            };
            rq["hub_oid"] = rq["id"] # for compat
            
            for ob in rarg:
                if not ob in rq: rq[ob] = rarg[ob]
            
            abortFlag = {"ABORT": False}

            self.pipes[rq["id"]] = {"rq": rq, "request": request, "pos": READBYTES, "ts": time.time(), "uri": request.path, "dir": 0, "arg": rarg, "abort": abortFlag};
            request.notifyFinish().addErrback(self._responseFailed, abortFlag)
            
            if DEBUG>1: print "render_GET: requesting first block"

            self.requestHub.self_receive(GETPIPE_TERMNAME, copy.copy(rq)) # # NO!! do not send to session
            # # we need to expose a mechanism to resolver normal requests (for example, have a special session ID for external RQs)
            

            
            return  server.NOT_DONE_YET
            
            
            
        return "OK"
    
    # errback to cancel request
    def _responseFailed(self, err, call):
        call["ABORT"] = True
        # need to somehow cancel connection other way!!!
    
    def blobreceived(self, rq):
        # TODO HERE
        # + we should then watch for this ID either in DB or wait till received
        # + then send. If the length is less than 100k -> finish the connection and remove
        # + else - retrieve and send next chunk
        # + timeout pipes
        # + watch for errors (for eaxmple object not found by path)
        # - handle pipe for read() and write() by different paths
        # - close incoming POST connection upon first rq receipt (with offset 0)
        
        if DEBUG>1: print "blob_received:", repr(rq)

        # rq = simplejson.loads(rq["body"]) 
        
        if not rq["id"] in self.pipes:
            print "ASSERT!!! -> request %s not found in PIPES" % rq["id"]
            return
        
        if rq["status"] != "OK" and self.pipes[rq["id"]]["request"]: # checking for request is required for POST pipe
            # parse error into HTTP errors
            if rq["status"] == "EPERM":
                self.pipes[rq["id"]]["request"].setResponseCode(403);
                self.pipes[rq["id"]]["request"].write("Forbidden")
                self.pipes[rq["id"]]["request"].finish();
            elif "not found" in rq["result"]:
                self.pipes[rq["id"]]["request"].setResponseCode(404);
                self.pipes[rq["id"]]["request"].write("Object not found: "+rq["result"])
                self.pipes[rq["id"]]["request"].finish();
            else:
                self.pipes[rq["id"]]["request"].setResponseCode(500);
                self.pipes[rq["id"]]["request"].write("Error at callee side: "+rq["result"])
                self.pipes[rq["id"]]["request"].finish();
            del self.pipes[rq["id"]]
            return
                    
        
        if self.pipes[rq["id"]]["dir"]: # 1 means "blob POST"
            # now that we received the data, we may safely close request
            if self.pipes[rq["id"]]["request"]:
                self.pipes[rq["id"]]["request"].finish();
                print "Closing request"
            # warning! different ABI here from the below!
            self.send_blob(self.pipes[rq["id"]]["uri"], self.pipes[rq["id"]]["fd"], self.pipes[rq["id"]]["isblob"], self.pipes[rq["id"]]["pos"], READBYTES, None, self.pipes[rq["id"]]["arg"])
            if rq["id"] in self.pipes: del self.pipes[rq["id"]] # may have been removed?
            else: print "WARN! pipes cleaned out before we do!"
        else:
            
            if self.pipes[rq["id"]]["abort"]["ABORT"]: # esoteric method of aborting
                return;
            
            blobid = rq["result"] # it may be a blobid OR a resulting STRING!!!

            #try:
            
            # OMG!! very tiny chance of failure here (not completely robust) TODO address this later: properly escape/unescape Blobs
            if blobid[0:5] == "Blob(" and blobid[-1] == ")":
                isblob = True
            else:
                isblob = False
            
            
            #except:
            #    if rq["id"] in self.pipes: del pipes[rq["id"]]
            #    return # just ignore malformed response
            rqid = rq["id"]


            # slightly inefficient memory usage
            rq2 = {
                    "id": genhash(10)+str(newId()), 
                    #"terminal_id": "/"+GETPIPE_TERMNAME, # set in rarg
                    #// optional but mandatory for local calls
                    "caller_type": "",
                    "caller_uri": "/"+GETPIPE_TERMNAME,
                    "caller_security": "",
                    #// now the actual params
                    "uri": self.pipes[rq["id"]]["uri"],
                    "method": "read",
                    "args": [self.pipes[rq["id"]]["pos"],READBYTES]
            };
            rq2["hub_oid"] = rq2["id"] # for compat
            
            # at this stage rq["id"] get messed...
            rarg = self.pipes[rq["id"]]["arg"]
            rarg.update(rq2)
            rq2 = rarg
            
            


            if isblob:
                b = self.get_blob(None, blobid)
                if not b is None:
                    print "blobIS there! trying to get", blobid, " POS ", self.pipes[rqid]["pos"]
                    if self.pipes[rqid]["pos"] == READBYTES:
                        # get type and set response header
                        ctype = getType(file=cStringIO.StringIO(b))
                        self.pipes[rqid]["request"].setHeader("Content-Type", str(ctype))
                        print "SETTING CONTENT-TYPE to ", ctype
                    self.pipes[rqid]["request"].write(b);
                    if len(b) < READBYTES:
                        self.pipes[rqid]["request"].finish();
                        del self.pipes[rqid]
                        print "FINISH", blobid
                    else:
                        # request next block
                        self.pipes[rq2["id"]] = {"rq": rq2, "request": self.pipes[rqid]["request"], "pos": self.pipes[rqid]["pos"]+READBYTES, "ts":time.time(), "uri": self.pipes[rqid]["uri"], "dir": 0, "arg": rarg, "abort": self.pipes[rqid]["abort"]}
                        print "requesting NEXT block!", blobid
                        self.requestHub.self_receive(GETPIPE_TERMNAME, copy.copy(rq2)) # NO!! do not send to session
                        del self.pipes[rqid]
                        
                else:
                    # wait for blob to arrive here!
                    print "will wait for blob", blobid
                    self.waitblob[blobid] = rq # TODO: re-invoke blobreceived, delete from waitblob
            else:
                # we use rqid instead of rq["id"] since it is messed (programming error?)
                self.pipes[rqid]["request"].write(blobid); # blobid is not a blob id here ;-)
                if len(blobid) < READBYTES:
                    self.pipes[rqid]["request"].finish();
                    del self.pipes[rqid]
                else:
                    # request next block
                    # COPYPASTE WARNING HERE!

                    self.pipes[rq2["id"]] = {"rq": rq2, "request": self.pipes[rqid]["request"], "pos": self.pipes[rqid]["pos"]+READBYTES, "ts": time.time(), "uri": self.pipes[rqid]["uri"], "dir": 0, "arg": rarg, "abort": self.pipes[rqid]["abort"]}
                    self.requestHub.self_receive(GETPIPE_TERMNAME, copy.copy(rq2)) ## NO!! do not send to session
                    
                    del self.pipes[rqid]
                    #print "rq2 is", rq2["id"], (rq2["id"] in self.pipes)
                    # END COPYPASTE WARNING!!!@!@
    def preinit(self):
        if not self.clean1: 
            # XXX the ugly initializtiona way
            self.clean1 = LoopingCall(self.conn_checkdrop)
            self.clean1.start(CONN_TIMEOUT)
            self.clean2 = LoopingCall(self.blob_checkdrop)
            self.clean2.start(BLOB_TIMEOUT)
            self.clean3 = LoopingCall(self.pipe_checkdrop)
            self.clean3.start(PIPE_TIMEOUT)
            
            # now init the requestHUb object
            self.requestHub = h;

            termid = GETPIPE_TERMNAME
            self.requestHub.register_session(termid, self.blobreceived); 
            

    def render_POST(self, request):
        #[]
        if DEBUG>1:print "POST! prepath=", request.prepath[0] # #####################
        self.preinit();
        
        if DEBUG>3:print "preinit done!" # #####################
        if "blobsend" == request.prepath[0]:
            #pass # do receive the blob in base64
            if DEBUG>3:print "blobsend!" # #####################
            blob = request.content.read(); # the body of request, Google-Gears specific
            
            if DEBUG>3:print "blobsend: GOT POST BODY length: ", len(blob) # ############################################
            if DEBUG>4 and len(blob)<100: print "Blob contents:", repr(blob)
            try:
                blobid = request.args['blobid'][0]
                sess = request.args['blob_session'][0]
            except KeyError:
                return "EPARM"

            # now store the blob in the availability list
            # and mark any waiting queues to start sending data [in fact, send data entirely]
            self.add_blob(sess, blobid, blob);
            return "OK"
        elif "base64send" == request.prepath[0]:
            try:
                b64blob = request.args['data'][0]
                blobid = request.args['blobid'][0]
                sess = request.args['blob_session'][0]
            except KeyError:
                return "EPARM"
            # now store the blob in the availability list
            # and mark any waiting queues to start sending data [in fact, send data entirely]
            self.add_blob(sess, blobid, b64blob.decode("hex")); 
            return "OK"

        else:
            # try to parse the POST in a multipart form
            # and then sequentally write it to receiver
            # returning the correct status (not found, forbidden, internal error or OK)
            
            # XXX DOC: the program must first make sure the ramstore object exists and is in a proper state
            #         (is empty or is set to appropriate length, supports BLOBs or UTF-8 TEXT)
            
            #fd = request.content # this is Gears way, not the MULTIPART way of browser
            
            # now, treat it as BLOB is the file is larger than 1000 kb
            # also treat it as blob if these 1000kb could not be converted in UTF-8
            
            #  Gears way
            #fd.seek(TREAT_AS_BLOB_SIZE)
            isblob = True # treat as blob by default
            
            #if not fd.read(1):
            if DEBUG > 4: 
                print "POST Args:"
                for ob in request.args:
                    print ">", ob, "Len:", 
                    print len(request.args[ob])
            if len(request.args['file'][0]) < TREAT_AS_BLOB_SIZE:
                #fd.seek(0)
                #r = fd.read()
                r = request.args['file']
                try:
                    r[0].decode("UTF-8")
                    isblob = False
                except UnicodeDecodeError:
                    pass
            
            #fd.seek(0)
            
            fd2 = cStringIO.StringIO()
            # fd2.write(fd.read()) # SHIT. why the FUCK do I need to copy it every time???
            fd2.write(request.args['file'][0]); # only one file is supported per upload!
            fd2.seek(0)
            
            # XXX DOC
            #         if the blob size is more than TREAT_AS_BLOB_SIZE = 1000000 bytes - send as Blob()
            #         else, try to encode the data in UTF-8 first
            #         if succeeded, deliver as TEXT argument, otherwise - as BLOB argument
            
            rarg = {}
            global terminals
            csession = request.getCookie("session")
            if csession in terminals:
                cterminal = terminals[csession]
            else:
                cterminal = GETPIPE_TERMNAME
            
            rarg["terminal_id"] = cterminal
            
            for v in request.args:
                if v!="file" and v!="terminal_id" and self.checkarg(request.args[v][0]): rarg[v] = request.args[v][0] # XXX DOC use only the FIRST entry parameter value
    
            self.send_blob(request.path, fd2, isblob, 0, READBYTES, request, rarg)
            return  server.NOT_DONE_YET
            
        return "OK"

    def checkarg(self, data):
        "check if data is an adequate argument to send in RQ object"
        # TODO: a more strict checking
        if len(data) > 100000: return False
        try:
            data.decode("UTF-8")
        except UnicodeDecodeError:
            return False
        # except:
        #   return False # if any other error
        return True

    def send_blob(self, uri, fd, isblob, pos=0, size=READBYTES, request = None, rarg = {}):
        
        rq = {
                "id": genhash(10)+str(newId()), 
                # "terminal_id": "/"+GETPIPE_TERMNAME, # set in rarg
                #// optional but mandatory for local calls
                "caller_type": "",
                "caller_uri": "/"+GETPIPE_TERMNAME,
                "caller_security": "",
                #// now the actual params
                "uri": uri,
                "method": "write",
        };
        rq["hub_oid"] = rq["id"] # for compat
        
        rarg.update(rq)
        
        rq = rarg
        # this is COSTYL development!
        if "status" in rq: 
            del rq["status"]
            print "send_blob(): ASSERT!! programming error in rarg"
        if "result" in rq: del rq["result"]
        
        #fd.seek(pos)
        data = fd.read(size)
        print "Data is:, repr(data),  of size: ", size, "got size:", len(data)
        print "Value is of length:", len(fd.getvalue())
        
        if isblob:
            # first, create a blobid and the blob
            blobid = "Blob(args."+genhash(15)+")"
            self.add_blob("NOSESSION", blobid, data); # session to be ignored
            if pos: rq["args"] = [blobid, pos]
            else: rq["args"] = [blobid] # to truncate data first to 0
        else:
            if pos: rq["args"] = [data.decode("UTF-8"),pos]
            else: rq["args"] = [data.decode("UTF-8")]

        if len(data) == size: self.pipes[rq["id"]] = {"pos": pos+size, "ts": time.time(), "uri": uri, "isblob": isblob, "fd": fd, "dir": 1, "request" : request, "arg": rarg};
        else: 
            if request: request.finish()
        print "SEND_BLOB: issuing next WRITE operation!:", rq
        self.requestHub.self_receive(GETPIPE_TERMNAME, copy.copy(rq))

import storage

global bp
bp = BlobPipe()
storage.bp = bp

site = server.Site(bp)


import socket
if CONNECT_HUB_DEFAULT and (not (socket.gethostname() in DONTLOOP)):   
    try:
        c = dbconn.cursor()
        c.execute("insert into reg (name, key, identity, created, accessed) values (%s,%s,%s,%s,%s)", (LOCAL["terminal_id"],LOCAL["terminal_key"],"LOCAL", int(time.time()),int(time.time())))
        dbconn.commit()
        c.close()
    except psycopg2.IntegrityError, e:
        if DEBUG: print "Failed to create default local hub link; trying to update"
        c.close()
	dbconn.rollback()
        c = dbconn.cursor()
        c.execute("update reg set key=%s where name=%s", (LOCAL["terminal_key"], LOCAL["terminal_id"]))
	dbconn.commit()
    hr = HubRelay(LOCAL, REMOTE)

reactor.connectTCP('localhost', STOMP_PORT, h)
reactor.listenTCP(BLOB_PORT, site)
reactor.run()

