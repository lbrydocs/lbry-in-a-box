from jsonrpc.proxy import JSONRPCProxy
from bitcoinrpc.authproxy import AuthServiceProxy
import subprocess
import json
import time
import string 

lbrycrd_rpc_user='rpcuser'
lbrycrd_rpc_pw='jhopfpusrx'
lbrycrd_rpc_ip='127.0.0.1'
lbrycrd_rpc_port='19001'
lbryum_lbrycrd_rpc_port = '19011'
lbrynet_rpc_port = '5279'
dht_rpc_port = '5278'
reflector_rpc_port = '5277'

lbrynets={}
lbrynets['lbrynet'] = JSONRPCProxy.from_url("http://localhost:{}/lbryapi".format(lbrynet_rpc_port))
lbrynets['dht'] = JSONRPCProxy.from_url("http://localhost:{}/lbryapi".format(dht_rpc_port))
lbrynets['reflector'] = JSONRPCProxy.from_url("http://localhost:{}/lbryapi".format(reflector_rpc_port))

DOCKER_LOG_FILE='tmp.log'
NUM_INITIAL_BLOCKS_GENERATED = 150

def get_lbrycrd_authproxy(instance):
    if instance == 'lbryum-server':
        port = lbryum_lbrycrd_rpc_port
    elif instance == 'lbrycrd':
        port = lbrycrd_rpc_port
    else:
        raise Exception('unhandled type')
    return AuthServiceProxy("http://{}:{}@{}:{}".format(lbrycrd_rpc_user,lbrycrd_rpc_pw,
                                                            lbrycrd_rpc_ip,port))

lbrycrds={}
lbrycrds['lbrycrd'] = get_lbrycrd_authproxy('lbrycrd')
lbrycrds['lbryum-server'] = get_lbrycrd_authproxy('lbryum-server')


def shell_command(command):
    p = subprocess.Popen(command,shell=True,stdout=subprocess.PIPE)
    out,err = p.communicate()
    return out,err

def call_lbrycrd(method, *params):
    lbrycrd = AuthServiceProxy("http://{}:{}@{}:{}".format(lbrycrd_rpc_user,lbrycrd_rpc_pw,
                                                            lbrycrd_rpc_ip,lbrycrd_rpc_port))
    return getattr(lbrycrd,method)(*params)


# call lbrycrd on lbryum server
def call_lbrycrd_lbryum_server(method, *params):
    lbrycrd = AuthServiceProxy("http://{}:{}@{}:{}".format(lbrycrd_rpc_user,lbrycrd_rpc_pw,
                                                            lbrycrd_rpc_ip,lbryum_lbrycrd_rpc_port))
    return getattr(lbrycrd,method)(*params)

def call_lbryum(method, *params):
    params_str = ' '.join([json.dumps(p) for p in params])
    lbryum_cmd = "/src/lbryum_rpc_client.py {} {}".format(method,params_str)
    cmd = 'docker exec -it lbryinabox_lbryum_1 /app/bin/python {}'.format(lbryum_cmd)
    out,err = shell_command(cmd)
    try:
        out = json.loads(out)        
    except ValueError as e:
        print out
        print e
        raise
    return out

# wait till txid appears on lbrycrd instance, 
# return True if it does within timeout
def wait_for_lbrynet_sync(instance, txid, timeout=90):
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            lbrycrd_out = lbrycrds[instance].getrawtransaction(txid)
        except Exception as e:
            pass
        else:
            if all(c in string.hexdigits for c in lbrycrd_out):
                return True
            else:
                raise Exception('got unexpected output:{}'.format(out))
        time.sleep(1)
    return False


def docker_compose_build():
    # Make sure to rebuild docker instances
    out,err=shell_command('docker-compose down')
    out,err=shell_command('docker-compose rm -f')
    out,err=shell_command('docker-compose build')
    print out
    if err != None:
        raise Exception("Failed to build")
    out,err=shell_command('docker-compose up > {}&'.format(DOCKER_LOG_FILE))




