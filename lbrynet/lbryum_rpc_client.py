#!/usr/bin/env python2
# utility program for calling lbryum commands from command line
import json
import sys
from jsonrpc.proxy import JSONRPCProxy
jsonrpc  = JSONRPCProxy.from_url('http://localhost:7777','')

def json_decode(s):
    try:
        out = json.loads(s)
    except ValueError:
        out = s
    return out

if __name__ == '__main__':
    cmdname = sys.argv[1]
    cmds = sys.argv[2:]
    cmds = [json_decode(cmd) for cmd in cmds]
    out = getattr(jsonrpc,cmdname)(*cmds)
    print json.dumps(out)
