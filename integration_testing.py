"""
Integration testing using lbry-in-a-box

This will stop,rebuild and launch docker containers for lbry in a box,
and than run integration testing

"""

import unittest
import subprocess
import time
from jsonrpc.proxy import JSONRPCProxy
from bitcoinrpc.authproxy import AuthServiceProxy

from urllib2 import URLError
from httplib import BadStatusLine
from socket import error
import os
import json
import string

lbrycrd_rpc_user='rpcuser'
lbrycrd_rpc_pw='jhopfpusrx'
lbrycrd_rpc_ip='127.0.0.1'
lbrycrd_rpc_port='19001'
lbrynet_rpc_port = '5279'
dht_rpc_port = '5278'
reflector_rpc_port = '5277'

lbrynets={}
lbrynets['lbrynet'] = JSONRPCProxy.from_url("http://localhost:{}/lbryapi".format(lbrynet_rpc_port))
lbrynets['dht'] = JSONRPCProxy.from_url("http://localhost:{}/lbryapi".format(dht_rpc_port))
lbrynets['reflector'] = JSONRPCProxy.from_url("http://localhost:{}/lbryapi".format(reflector_rpc_port))

test_metadata = {
    'license': 'NASA',
    'description': 'test_description',
    'language': 'en',
    'author': 'test_author',
    'title': 'test_title',
    'nsfw': False,
}

DOCKER_LOG_FILE='tmp.log'
NUM_INITIAL_BLOCKS_GENERATED = 150

def shell_command(command):
    p = subprocess.Popen(command,shell=True,stdout=subprocess.PIPE)
    out,err = p.communicate()
    return out,err

def call_lbrycrd(method, *params):
    lbrycrd = AuthServiceProxy("http://{}:{}@{}:{}".format(lbrycrd_rpc_user,lbrycrd_rpc_pw,
                                                            lbrycrd_rpc_ip,lbrycrd_rpc_port))
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
        raise
    return out

# wrapper function just to see where we are in the test
def print_func(func):
    def wrapper(*args,**kwargs):
        print("Running:{}".format(func.func_name))
        return func(*args,**kwargs)
    return wrapper

class LbrynetTest(unittest.TestCase):

    def test_lbrynet(self):

        self._test_lbrynet_startup()
        self._test_misc()
        self._test_recv_and_send()
        self._test_publish('testname', claim_amount=1,)
        self._test_publish('testname2', claim_amount=1, key_fee=1.0)
        self._test_update()
        self._test_support()
        self._test_abandon()
        self._test_channels()
        self._test_uri()
        # TODO: should try to remove all errors here, raise error if found
        print("Printing ERRORS found in log:")
        out,err = shell_command('grep ERROR {}'.format(DOCKER_LOG_FILE))
        print out

    @unittest.skip("skipping lbryum specific tests")
    def test_lbryum(self):
        self._test_lbryum_invalid_update()


    # randomly generate a test file on lbrynet instance
    def _generate_test_file(self, lbrynet_instance_str, file_size_bytes, file_path):
        cmd = 'docker exec -it lbryinabox_{}_1 dd if=/dev/urandom of={} bs={} count=1'.format(
            lbrynet_instance_str, file_path, file_size_bytes)
        out,err = shell_command(cmd)

    # get sha1sum of a file on lbrynet instance
    def _get_sha1sum_of_file(self, lbrynet_instance_str, file_path):
        cmd = 'docker exec -it lbryinabox_{}_1 sha1sum {}'.format(lbrynet_instance_str, file_path)
        out,err = shell_command(cmd)
        sha1sum =  out.split()[0]
        return sha1sum

    # check if file exists on a lbrynet isntance
    def _check_has_file(self, lbrynet_instance_str, file_path):
        cmd = 'docker exec -it lbryinabox_{}_1 find {}'.format(lbrynet_instance_str, file_path)
        out,err = shell_command(cmd)
        return 'No such file' not in out and file_path in out

    def _increment_blocks(self, num_blocks):
        LBRYNET_BLOCK_SYNC_TIMEOUT = 60

        out = call_lbrycrd('generate',num_blocks)
        self.assertEqual(len(out),num_blocks)
        for blockhash in out:
            self._is_blockhash(blockhash)

        # wait till all lbrynet instances in sync with the
        # tip of the blockchain
        best_block_hash = call_lbrycrd('getbestblockhash')
        self._is_blockhash(best_block_hash)
        start_time = time.time()
        while time.time() - start_time < LBRYNET_BLOCK_SYNC_TIMEOUT:
            # wait till all lbrynets blockhash are best
            if all([lbrynet.get_best_blockhash() == best_block_hash for lbrynet in lbrynets.values()]):
                # wait till lbryum blockhash is best
                if call_lbryum('getbestblockhash') == best_block_hash:
                    return
            time.sleep(1)
        self.fail('Lbrynet block sync timed out')

    def _is_txid(self, txid):
        self.assertEqual(len(txid),64)

    def _is_blockhash(self, blockhash):
        self.assertEqual(len(blockhash),64)

    def _wait_till_balance_equals(self,lbrynet,amount,less_than=False):
        LBRYNET_SYNC_TIMEOUT = 90
        start_time = time.time()
        while time.time() - start_time < LBRYNET_SYNC_TIMEOUT:
            if not less_than and lbrynet.get_balance() == amount:
                return
            if less_than and lbrynet.get_balance() < amount:
                return
            time.sleep(1)
        self.fail('Lbrynet failed to sync balance in time')

    # wait till txid appears on lbrycrd
    def _wait_for_lbrynet_sync(self,txid=None):
        LBRYNET_SYNC_TIMEOUT = 90
        start_time = time.time()
        while time.time() - start_time < LBRYNET_SYNC_TIMEOUT:
            try:
                lbrycrd_out = call_lbrycrd('getrawtransaction',txid)
            except Exception as e:
                pass
            else:
                if all(c in string.hexdigits for c in lbrycrd_out):
                    return
                else:
                    self.fail('got unexpected output:{}'.format(out))
            time.sleep(1)
        self.fail('Lbrynet failed to synce txid in time')

    # send amount from lbrycrd to lbrynet instance
    def _send_from_lbrycrd(self, amount, to_lbrynet):
        prev_balance = to_lbrynet.get_balance()
        address = to_lbrynet.get_new_address()
        out = to_lbrynet.wallet_public_key({'address':address})
        self.assertEqual(len(out), 1)

        out = call_lbrycrd('sendtoaddress',address,amount)
        self._is_txid(out)
        self._increment_blocks(6)
        self._wait_till_balance_equals(to_lbrynet,prev_balance+amount)


    # check claim for name is occupied by txid/nout
    def _check_claim_state(self, name, txid, nout, amount, effective_amount=None):
        if effective_amount is None:
            effective_amount = amount
        # check lbrycrd
        out = call_lbrycrd('getvalueforname', name)
        self.assertEqual(out['txid'],txid)
        self.assertEqual(out['n'],nout)
        self.assertEqual(out['amount'],amount*100000000)
        #self.assertEqual(out['effective amount'],effective_amount*100000000)

        # check lbryum
        out = call_lbryum('getvalueforname', name)
        self.assertEqual(out['txid'],txid)
        self.assertEqual(out['nout'],nout)

        # check lbrynet
        out= lbrynets['lbrynet'].resolve({'uri':name})
        if 'claim' in out:
            self.assertEqual(out['claim']['txid'],txid)
            self.assertEqual(out['claim']['nout'],nout)
        elif 'certificate' in out:
            self.assertEqual(out['certificate']['txid'],txid)
            self.assertEqual(out['certificate']['nout'],nout)

    # check that name is unclaimed
    def _check_unclaimed(self, name):
        out = call_lbrycrd('getvalueforname', name)
        self.assertEqual({},out)

        out = call_lbryum('getvalueforname', name)
        self.assertTrue('error' in out)
        self.assertEqual(out['error'],'name is not claimed')

        out= lbrynets['lbrynet'].resolve({'uri':name})
        self.assertEqual(None, out)

    def _check_lbrynet_init(self,lbrynet):
        try:
            lbrynet_status = lbrynet.status()
        except (URLError,error,BadStatusLine) as e:
            return False

        if lbrynet_status['is_running'] == True and lbrynet_status['blockchain_status']['blocks'] == NUM_INITIAL_BLOCKS_GENERATED:
            self.assertEqual(0, lbrynet.get_balance())
            #TODO: this should be True
            #self.assertEqual(True, lbrynet_status['is_first_run'])
            self.assertEqual(0, lbrynet_status['blocks_behind'])
            return True
        else:
            return False

    @print_func
    def _test_lbrynet_startup(self):
        LBRYNET_STARTUP_TIMEOUT = 180

        # Make sure to rebuild docker instances
        out,err=shell_command('docker-compose down')
        out,err=shell_command('docker-compose rm -f')
        out,err=shell_command('docker-compose build')
        print out
        if err != None:
            self.fail("Failed to build")
        out,err=shell_command('docker-compose up > {}&'.format(DOCKER_LOG_FILE))

        start_time = time.time()
        while time.time() - start_time < LBRYNET_STARTUP_TIMEOUT:
            if all([self._check_lbrynet_init(lbrynet) for lbrynet in lbrynets.values()]):
                return
            time.sleep(3)
        self.fail('Lbrynet failed to start up')

    @print_func
    def _test_misc(self):
        #TODO: these command fail when claimtrie is empty  (no claim has been made) 
        # test resolve_name for unresolveable name
        #out = lbrynets['lbrynet'].resolve_name({'name':'some_unclaimed_name'})
        #self.assertEqual(None, out)
        #out = lbrynets['lbrynet'].resolve({'uri':'some_unclaimed_name'})
        #self.assertEqual(None,out)
        pass

    """
    receive balance from lbrycrd to lbrynet
    make sure this test gets run first, so
    lbrynet has credits required to run some commands
    """
    @print_func
    def _test_recv_and_send(self):
        RECV_AMOUNT = 10
        SEND_AMOUNT = 1
        LBRYNET_SEND_SYNC_TIMEOUT = 80
        self._send_from_lbrycrd(RECV_AMOUNT,lbrynets['lbrynet'])

        # create lbrycrd address
        address = call_lbrycrd('getnewaddress','test')
        out = call_lbrycrd('getbalance','test')
        self.assertEqual(0,out)

        # send from lbrynet to lbrycrd
        out = lbrynets['lbrynet'].send_amount_to_address({'amount':SEND_AMOUNT, 'address':address})
        self.assertEqual(out,True)

        # wait for lbrycrd to sync balance
        start_time = time.time()
        while call_lbrycrd('getreceivedbyaccount','test',0) < SEND_AMOUNT:
            if time.time() - start_time > LBRYNET_SEND_SYNC_TIMEOUT:
                self.fail('Lbrynet send failed to sync within time')
            time.sleep(0.1)
        self._increment_blocks(6)
        out = call_lbrycrd('getbalance', 'test')
        self.assertEqual(SEND_AMOUNT, out)

    def _publish(self, claim_name, claim_amount, key_fee, channel_name=None, test_pub_file_size=1024):

        test_pub_file_name = claim_name+'.txt'
        test_pub_file_dir = '/src/lbry'
        test_pub_file = os.path.join(test_pub_file_dir,test_pub_file_name)
        expected_download_file = os.path.join('/data/Downloads/',test_pub_file_name)

        # make sure we have enough to claim the amount
        out = lbrynets['lbrynet'].get_balance()
        self.assertTrue(out >= claim_amount)

        key_fee_address = None
        if key_fee != 0:
            key_fee_address = lbrynets['lbrynet'].get_new_address()
            test_metadata["fee"]= {'LBC': {"address": key_fee_address, "amount": key_fee}}
        elif key_fee == 0 and 'fee' in test_metadata:
            del test_metadata['fee']

        self._generate_test_file('lbrynet', test_pub_file_size, test_pub_file)

        out = lbrynets['lbrynet'].publish({
            'name':claim_name,'file_path':test_pub_file,'bid':claim_amount,
            'metadata':test_metadata, 'channel_name':channel_name})
        self.assertTrue('txid' in out)
        self.assertTrue('nout' in out)
        self.assertTrue('claim_id' in out)
        self.assertTrue('tx' in out)
        self.assertTrue('fee' in out)
        publish_txid = out['txid']
        publish_nout = out['nout']
        claim_id = out['claim_id']
        self._is_txid(publish_txid)
        self.assertTrue(isinstance(publish_nout,int))

        self._wait_for_lbrynet_sync(out['txid'])
        self._increment_blocks(6)
        out = {'publish_txid':publish_txid, 'publish_nout':publish_nout,'claim_id':claim_id,'key_fee_address':key_fee_address,
            'expected_download_file':expected_download_file,'file_name':test_pub_file_name}
        return out

    # makes sure all key,value present in expected_dict is present
    # and equivalent acutal_dict, return True if so
    def _compare_dict(self, expected_dict, actual_dict):
        for key,val in expected_dict.iteritems():
            if key not in actual_dict:
                #print("{} not found".format(key))
                return False
            if expected_dict[key] != actual_dict[key]:
                #print("{} does not equal {} for key {}".format(expected_dict[key],actual_dict[key],key))
                return False
        return True

    # test publishing from lbrynet, and test to see if we can download from dht
    @print_func
    def _test_publish(self, claim_name, claim_amount, key_fee = 0):
        publish_out = self._publish(claim_name, claim_amount, key_fee)
        publish_txid = publish_out['publish_txid']
        publish_nout = publish_out['publish_nout']
        claim_id = publish_out['claim_id']
        key_fee_address = publish_out['key_fee_address']
        expected_download_file = publish_out['expected_download_file']
        publish_outpoint = publish_txid+':'+str(publish_nout)

        balance_before_key_fee = lbrynets['lbrynet'].get_balance()

        self._check_claim_state(claim_name, publish_out['publish_txid'],publish_out['publish_nout'], claim_amount)

        # check lbrynet claim states are updated
        out = lbrynets['lbrynet'].claim_show({'name':claim_name})
        self.assertEqual(claim_name, out['name'])
        self.assertEqual(publish_txid, out['txid'])
        self.assertEqual(publish_nout, out['nout'])
        self.assertEqual(claim_amount, out['amount'])
        #self.assertEqual([],out['supports'])
        sd_hash = out['value']['stream']['source']['source']

        out = lbrynets['lbrynet'].claim_list_mine()
        found = False
        for claim in out:
            if (claim['name'] == claim_name and
                claim['amount'] == claim_amount and
                claim['txid'] == publish_txid and
                claim['nout'] == publish_nout):
                found = True
        self.assertTrue(found)

        out = lbrynets['lbrynet'].claim_list({'name':claim_name})
        self.assertTrue('claims' in out)
        self.assertEqual(1, len(out['claims']))
        self.assertEqual(publish_txid, out['claims'][0]['txid'])
        self.assertEqual(publish_nout, out['claims'][0]['nout'])
        self.assertEqual(claim_amount, out['claims'][0]['amount'])

        expected_metadata={
            'license':test_metadata['license'],
            #'ver':test_metadata['ver'],
            'language':test_metadata['language'],
            'author':test_metadata['author'],
            'title':test_metadata['title'],
            #'sources':{'lbry_sd_hash':sd_hash},
            'nsfw':test_metadata['nsfw'],
            #'content_type':'text/plain',
            'description':test_metadata['description']
        }
        if key_fee != 0:
            #expected_metadata['fee'] = {'LBC': {"address": key_fee_address, "amount": key_fee}}
            expected_metadata['fee'] = {'currency':'LBC','address':key_fee_address,'amount':key_fee,'version':'_0_0_1'}
        out = lbrynets['lbrynet'].resolve_name({'name':claim_name})
        metadata = out['stream']['metadata']
        #TODO: need to compare entire claim_dict here
        self.assertTrue(self._compare_dict(expected_metadata,metadata))

        # TODO:need to check stream hash, points paid, written_bytes,
        # completed, stopped
        expected_file_info={
            'download_directory': '/data/Downloads',
            'name': claim_name,
            'download_path':publish_out['expected_download_file'],
            'file_name': publish_out['file_name'],
            'sd_hash': sd_hash,
            'suggested_file_name': publish_out['file_name'],
            'outpoint': publish_outpoint,
            'stream_name': publish_out['file_name'],
            'claim_id': claim_id,
        }

        # test download of own file
        out = lbrynets['lbrynet'].get({'uri':claim_name})
        self.assertTrue(self._compare_dict(expected_file_info, out))
        self.assertTrue(self._compare_dict(expected_metadata, out['metadata']['stream']['metadata']))

        # check file is under file_list
        out = lbrynets['lbrynet'].file_list()
        found_file = False
        for f in out:
            if self._compare_dict(expected_file_info,f):
                found_file = True
        self.assertTrue(found_file)

        # check file_list filtering works
        out = lbrynets['lbrynet'].file_list({'name':claim_name})
        self.assertEqual(1, len(out))
        self.assertTrue(self._compare_dict(expected_file_info,out[0]))
        self.assertTrue(self._compare_dict(expected_metadata, out[0]['metadata']['stream']['metadata']))

        out = lbrynets['lbrynet'].file_list({'sd_hash':sd_hash})
        self.assertEqual(1, len(out))
        self.assertTrue(self._compare_dict(expected_file_info,out[0]))
        self.assertTrue(self._compare_dict(expected_metadata, out[0]['metadata']['stream']['metadata']))

        out = lbrynets['lbrynet'].file_list({'file_name':publish_out['file_name']})
        self.assertEqual(1, len(out))
        self.assertTrue(self._compare_dict(expected_file_info,out[0]))
        self.assertTrue(self._compare_dict(expected_metadata, out[0]['metadata']['stream']['metadata']))

        # check that we can get its blob
        out = lbrynets['lbrynet'].blob_list({'sd_hash':sd_hash})
        self.assertEqual(1, len(out))
        blob_hash = out[0]

        # test download of own descriptor
        out = lbrynets['lbrynet'].descriptor_get({'sd_hash':sd_hash})
        self.assertTrue('blobs' in out)
        self.assertEqual(2, len(out['blobs']))
        self.assertEqual(blob_hash, out['blobs'][0]['blob_hash'])
        self.assertTrue('key' in out)
        self.assertTrue('stream_hash' in out)
        self.assertTrue('stream_name' in out)
        self.assertTrue('stream_type' in out)
        self.assertTrue('suggested_file_name' in out)


        # check reflector to see if it has hashes
        out = lbrynets['reflector'].get_blob_hashes()
        self.assertTrue(sd_hash in out)
        self.assertTrue(blob_hash in out)

        # test to see if we can get peers from the dht with the hash
        out = lbrynets['dht'].get_peers_for_hash({'blob_hash':sd_hash})
        self.assertEqual(2, len(out))

        # test to see if we can download from dht
        if key_fee != 0:
            # send key fee (plus additional amount to pay for tx fee) to dht if necessary
            self._send_from_lbrycrd(key_fee+1, lbrynets['dht'])

        dht_balance_before_get = lbrynets['dht'].get_balance()
        out = lbrynets['dht'].get({'uri':claim_name})
        self.assertTrue(self._compare_dict(expected_file_info, out))

        # wait for download to finish
        DOWNLOAD_TIMEOUT = 30
        start_time = time.time()
        while 1:
            out = lbrynets['dht'].file_list({'sd_hash':sd_hash})
            if out[0]['completed']:
                break
            if time.time() - start_time > DOWNLOAD_TIMEOUT:
                self.fail("Download failed to finish in time")
            time.sleep(1)

        # check to see if dht has the downloaded hashes
        out = lbrynets['dht'].get_blob_hashes()
        self.assertTrue(sd_hash in out)
        self.assertTrue(blob_hash in out)

        # check if dht has the file
        self.assertTrue(self._check_has_file('dht',publish_out['expected_download_file']))

        # check sha1sum of files are equivalent
        dht_sha1sum = self._get_sha1sum_of_file('dht', publish_out['expected_download_file'])
        lbrynet_sha1sum = self._get_sha1sum_of_file('lbrynet', publish_out['expected_download_file'])
        self.assertEqual(lbrynet_sha1sum, dht_sha1sum)

        # test to see if lbrynet received key fee
        # TODO: this needs to be fixed, does not reliablly work
        """
        if key_fee != 0:
            # wait for unconfirmed transaction to show up on dht
            start_time = time.time()
            while 1:
                out = lbrynets['dht'].transaction_list()
                if out[-1]['confirmations'] == 0 and out[-1]['value'] >= key_fee:
                    print out[-1]
                    txid = out[-1]['txid']
                    break
                time.sleep(1)
                if time.time() - start_time > 90:
                    self.fail('dht did not create transaction')

            self._wait_for_lbrynet_sync(txid)
            self._increment_blocks(6)
            self._wait_till_balance_equals(lbrynets['lbrynet'], balance_before_key_fee+key_fee)
        """

        # test file_delete on dht, keep file list on dht empty

        out = lbrynets['dht'].file_delete({'sd_hash':sd_hash})
        self.assertEqual(True,out)
        self.assertFalse(self._check_has_file('dht',publish_out['expected_download_file']))
        out = lbrynets['dht'].file_list()
        self.assertEqual(0, len(out))

    @print_func
    def _test_update(self, claim_name='updatetest', claim_amount=1, update_amount=2, key_fee=0 ):
        # publish
        publish_out = self._publish(claim_name, claim_amount, key_fee)
        self._check_claim_state(claim_name, publish_out['publish_txid'], publish_out['publish_nout'], claim_amount)

        #  download published file from dht
        out = lbrynets['dht'].get({'uri':claim_name})

        # update
        update_out = self._publish(claim_name, update_amount, key_fee)
        self._check_claim_state(claim_name, update_out['publish_txid'], update_out['publish_nout'], update_amount)

        # check file_list
        out = lbrynets['lbrynet'].file_list({'name':claim_name})
        self.assertEqual(2,len(out))

    @print_func
    def _test_abandon(self, claim_name='abandontest', claim_amount=1, key_fee=0):
        #TODO: should check download and redownload from DHT here

        # publish
        publish_out = self._publish(claim_name, claim_amount, key_fee)

        # abandon
        out = lbrynets['lbrynet'].claim_abandon({'claim_id':publish_out['claim_id']})
        self.assertTrue('txid' in out)
        self.assertTrue('fee' in out)
        self.assertTrue('tx' in out)

        self._wait_for_lbrynet_sync(out['txid'])
        self._increment_blocks(6)

        # check claimtrie state
        self._check_unclaimed(claim_name)


    @print_func
    def _test_support(self, claim_name='supporttest', claim_amount=1, key_fee=0, support_amount=1):
        # publish
        publish_out = self._publish(claim_name, claim_amount, key_fee)

        # support
        out = lbrynets['lbrynet'].claim_new_support({'name':claim_name,'claim_id':publish_out['claim_id'],'amount':support_amount})
        self.assertTrue('txid' in out)
        self.assertTrue('nout' in out)
        self.assertTrue('fee' in out)

        self._wait_for_lbrynet_sync(out['txid'])
        self._increment_blocks(6)

        out=lbrynets['lbrynet'].claim_show({'name':claim_name})
        self.assertEqual(claim_name, out['name'])
        self.assertEqual(publish_out['publish_txid'], out['txid'])
        self.assertEqual(publish_out['publish_nout'], out['nout'])
        #self.assertEqual(claim_amount+support_amount, out['effective_amount'])
        #self.assertEqual(1,len(out['supports']))


    @print_func
    def _test_channels(self, channel_name='@testchannel', claim_name='channelclaim', claim_amount=1):

        out = lbrynets['lbrynet'].channel_list_mine()
        self.assertEqual(0,len(out))

        # claim channel
        channel_out = lbrynets['lbrynet'].channel_new({'channel_name':channel_name,'amount':claim_amount})
        self.assertTrue('tx' in channel_out)
        self.assertTrue('txid' in channel_out)
        self.assertTrue('nout' in channel_out)
        self.assertTrue('claim_id' in channel_out)

        self._wait_for_lbrynet_sync(channel_out['txid'])
        self._increment_blocks(6)

        self._check_claim_state(channel_name,channel_out['txid'],channel_out['nout'],claim_amount)

        out = lbrynets['lbrynet'].channel_list_mine()
        self.assertEqual(1, len(out))

        publish_out = self._publish(claim_name, claim_amount, key_fee=0, channel_name=channel_name)

        out = lbrynets['lbrynet'].resolve({'uri':claim_name})
        self.assertEqual(out['claim']['txid'], publish_out['publish_txid'])
        self.assertEqual(out['claim']['nout'], publish_out['publish_nout'])
        self.assertEqual(out['claim']['nout'], publish_out['publish_nout'])
        self.assertEqual(out['claim']['channel_name'], channel_name)
        self.assertTrue(out['claim']['has_signature'])

        out = lbrynets['lbrynet'].resolve({'uri':channel_name})
        self.assertEqual(out['certificate']['txid'],channel_out['txid'])
        self.assertEqual(out['certificate']['nout'],channel_out['nout'])

        self.assertEqual(len(out['claims_in_channel']),1)
        self.assertEqual(out['claims_in_channel'][0]['name'],claim_name)
        self.assertEqual(out['claims_in_channel'][0]['txid'],publish_out['publish_txid'])
        self.assertEqual(out['claims_in_channel'][0]['nout'],publish_out['publish_nout'])

    @print_func
    def _test_uri(self):
        out = lbrynets['lbrynet'].resolve({"uri":"something_unclaimed:1"})
        self.assertEqual(None, out)

    @print_func
    def _test_lbryum_invalid_update(self):
        # this test makes sure that invalid updates do not make it in the claim trie

        address = call_lbryum('getunusedaddress')

        out = call_lbrycrd('sendtoaddress',address,1)
        self._is_txid(out)
        self._increment_blocks(6)

        claim_out = call_lbryum('claim','invalidupdate','test',0.01,None,True,None,None,None,True,True,
            True)
        self._wait_for_lbrynet_sync(claim_out['txid'])
        self._increment_blocks(6)

        claim_out_2 = call_lbryum('claim','unrelatedupdate','test',0.01,None,True,None,None,None,True,True,
            True)
        self._wait_for_lbrynet_sync(claim_out_2['txid'])
        self._increment_blocks(6)

        # this update is invalid
        update_out = call_lbryum('update','invalidupdate','test2',0.1, None, claim_out['claim_id'], claim_out_2['txid'], claim_out_2['nout'],True,None,
            None, None, True, True)
        self._wait_for_lbrynet_sync(update_out['txid'])
        self._increment_blocks(6)

        self._check_claim_state('invalidupdate',claim_out['txid'],claim_out['nout'],0.01)

        out=call_lbryum('getclaimbyid',claim_out['claim_id'])
        self.assertEqual(out['txid'],claim_out['txid'])
        self.assertEqual(out['nout'],claim_out['nout'])

        # this update is valid
        update_out = call_lbryum('update','invalidupdate','test2',0.1, None, claim_out['claim_id'], claim_out['txid'], claim_out['nout'],True,None,
            None, None, True, True)
        self._wait_for_lbrynet_sync(update_out['txid'])
        self._increment_blocks(6)

        out=call_lbryum('getclaimbyid',claim_out['claim_id'])
        self.assertEqual(out['txid'],update_out['txid'])
        self.assertEqual(out['nout'],update_out['nout'])


if __name__ == '__main__':

    unittest.main()


