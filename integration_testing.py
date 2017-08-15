"""
Integration testing using lbry-in-a-box

This will stop,rebuild and launch docker containers for lbry in a box,
and than run integration testing

"""

import unittest
from urllib2 import URLError,HTTPError
from httplib import BadStatusLine
from socket import error
import os

from test_utils import *

test_metadata = {
    'license': 'NASA',
    'description': 'test_description',
    'language': 'en',
    'author': 'test_author',
    'title': 'test_title',
    'nsfw': False,
}


class LbrynetTest(unittest.TestCase):
    def test_lbrynet(self):

        self._test_lbrynet_startup()
        self._test_recv_and_send()

        self._test_publish('testname', claim_amount=1, )
        self._test_publish('testname2', claim_amount=1, key_fee=1.0)

        self._test_batch_cmds()
        self._test_update()
        self._test_abandon()
        self._test_support()

        self._test_invalid_claims()

        self._test_channels()
        self._test_uri()
        self._test_misc()
        # TODO: should try to remove all errors here, raise error if found
        print("Printing ERRORS found in log:")
        out, err = shell_command('grep ERROR {}'.format(DOCKER_LOG_FILE))
        print out

    # randomly generate a test file on lbrynet instance
    def _generate_test_file(self, lbrynet_instance_str, file_size_bytes, file_path):
        cmd = 'docker exec -it lbryinabox_{}_1 dd if=/dev/urandom of={} bs={} count=1'.format(
            lbrynet_instance_str, file_path, file_size_bytes)
        out, err = shell_command(cmd)

    # get sha1sum of a file on lbrynet instance
    def _get_sha1sum_of_file(self, lbrynet_instance_str, file_path):
        cmd = 'docker exec -it lbryinabox_{}_1 sha1sum {}'.format(lbrynet_instance_str, file_path)
        out, err = shell_command(cmd)
        sha1sum = out.split()[0]
        return sha1sum

    # check if file exists on a lbrynet isntance
    def _check_has_file(self, lbrynet_instance_str, file_path):
        cmd = 'docker exec -it lbryinabox_{}_1 find {}'.format(lbrynet_instance_str, file_path)
        out, err = shell_command(cmd)
        return 'No such file' not in out and file_path in out

    def _increment_blocks(self, num_blocks):
        LBRYNET_BLOCK_SYNC_TIMEOUT = 60

        out = lbrycrds['lbrycrd'].generate(num_blocks)
        self.assertEqual(len(out), num_blocks)
        for blockhash in out:
            self._is_blockhash(blockhash)

        # wait till all lbrynet instances in sync with the
        # tip of the blockchain
        best_block_hash = lbrycrds['lbrycrd'].getbestblockhash()
        self._is_blockhash(best_block_hash)
        start_time = time.time()
        while time.time() - start_time < LBRYNET_BLOCK_SYNC_TIMEOUT:
            # wait till all lbrynets blockhash are best
            if all([lbrynet.status()['blockchain_status']['best_blockhash'] == best_block_hash for
                    lbrynet in lbrynets.values()]):
                # wait till lbryum blockhash is best
                if call_lbryum('getbestblockhash') == best_block_hash:
                    return
            time.sleep(1)
        self.fail('Lbrynet block sync timed out')

    def _is_txid(self, txid):
        self.assertEqual(len(txid), 64)

    def _is_blockhash(self, blockhash):
        self.assertEqual(len(blockhash), 64)

    def _wait_till_balance_equals(self, lbrynet, amount, less_than=False):
        LBRYNET_SYNC_TIMEOUT = 90
        start_time = time.time()
        while time.time() - start_time < LBRYNET_SYNC_TIMEOUT:
            if not less_than and lbrynet.wallet_balance() == amount:
                return
            if less_than and lbrynet.wallet_balance() < amount:
                return
            time.sleep(1)
        self.fail('Lbrynet failed to sync balance in time')

    # send amount from lbrycrd to lbrynet instance
    # return (txid of created transaction, address sent to)
    def _send_from_lbrycrd(self, amount, to_lbrynet):
        prev_balance = to_lbrynet.wallet_balance()
        address = to_lbrynet.wallet_new_address()
        out = to_lbrynet.wallet_public_key({'address': address})
        self.assertEqual(len(out), 1)

        out = lbrycrds['lbrycrd'].sendtoaddress(address, amount)
        self._is_txid(out)
        self._increment_blocks(6)
        self._wait_till_balance_equals(to_lbrynet, prev_balance + amount)
        return (out, address)

    # check claim for name is occupied by txid/nout
    def _check_claim_state(self, name, txid, nout, amount, effective_amount=None):
        if effective_amount is None:
            effective_amount = amount
        # check lbrycrd
        out = lbrycrds['lbrycrd'].getvalueforname(name)
        self.assertEqual(out['txid'], txid)
        self.assertEqual(out['n'], nout)
        self.assertEqual(out['amount'], amount * 100000000)
        # self.assertEqual(out['effective amount'],effective_amount*100000000)

        # check lbryum
        out = call_lbryum('getvalueforname', name)
        self.assertEqual(out['txid'], txid)
        self.assertEqual(out['nout'], nout)

        # check lbrynet
        out = lbrynets['lbrynet'].resolve({'uri': name, 'force': True})
        self.assertTrue(name in out)

        if 'claim' in out[name]:
            self.assertEqual(out[name]['claim']['txid'], txid)
            self.assertEqual(out[name]['claim']['nout'], nout)
        elif 'certificate' in out[name]:
            self.assertEqual(out[name]['certificate']['txid'], txid)
            self.assertEqual(out[name]['certificate']['nout'], nout)
        else:
            self.fail('{} is an invalid resolve'.format(out))

    # check that name is unclaimed
    def _check_unclaimed(self, name):
        out = lbrycrds['lbrycrd'].getvalueforname(name)
        self.assertEqual({}, out)

        out = call_lbryum('getvalueforname', name)
        self.assertTrue('error' in out)
        self.assertEqual(out['error'], 'name is not claimed')

        out = lbrynets['lbrynet'].resolve({'uri': name, 'force': True})
        self._check_lbrynet_unclaimed_resolve(out)

    def _check_lbrynet_unclaimed_resolve(self, out):
        for claim in out.values():
            self.assertTrue('error' in claim)
            # self.assertTrue('is unknown' in claim['error'])

    def _check_lbrynet_init(self, lbrynet):
        try:
            lbrynet_status = lbrynet.status()
        except (URLError, error, BadStatusLine) as e:
            return False
        is_running = lbrynet_status['is_running']
        blocks = lbrynet_status['blockchain_status']['blocks']
        if is_running == True and blocks == NUM_INITIAL_BLOCKS_GENERATED:
            self.assertEqual(0, lbrynet.wallet_balance())
            # TODO: this should be True
            # self.assertEqual(True, lbrynet_status['is_first_run'])
            self.assertEqual(0, lbrynet_status['blocks_behind'])
            return True
        else:
            return False

    @print_func
    def _test_lbrynet_startup(self):
        LBRYNET_STARTUP_TIMEOUT = 180
        docker_compose_build()
        start_time = time.time()
        while time.time() - start_time < LBRYNET_STARTUP_TIMEOUT:
            if all([self._check_lbrynet_init(lbrynet) for lbrynet in lbrynets.values()]):
                return
            time.sleep(3)
        self.fail('Lbrynet failed to start up')



    @print_func
    def _test_recv_and_send(self):
        """
        receive balance from lbrycrd to lbrynet
        make sure this test gets run first, so
        lbrynet has credits required to run some commands
        """
        RECV_AMOUNT = 10
        SEND_AMOUNT = 1
        LBRYNET_SEND_SYNC_TIMEOUT = 80
        txid, address = self._send_from_lbrycrd(RECV_AMOUNT, lbrynets['lbrynet'])

        # check transaction_show command
        out = lbrynets['lbrynet'].transaction_show({'txid':txid})
        self.assertTrue('inputs' in out)
        self.assertTrue('outputs' in out)
        self.assertTrue(any([o['address'] == address for o in out['outputs']]))


        # create lbrycrd address
        address = lbrycrds['lbrycrd'].getnewaddress('test')
        out = lbrycrds['lbrycrd'].getbalance('test')
        self.assertEqual(0, out)

        # test error when trying to send more than what we have
        with self.assertRaises(HTTPError):
            out = lbrynets['lbrynet'].send_amount_to_address(
                {'amount':RECV_AMOUNT+10, 'address':address})

        # send from lbrynet to lbrycrd
        out = lbrynets['lbrynet'].send_amount_to_address(
            {'amount': SEND_AMOUNT, 'address': address})
        self.assertEqual(out, True)

        # wait for lbrycrd to sync balance
        start_time = time.time()
        while lbrycrds['lbrycrd'].getreceivedbyaccount('test', 0) < SEND_AMOUNT:
            if time.time() - start_time > LBRYNET_SEND_SYNC_TIMEOUT:
                self.fail('Lbrynet send failed to sync within time')
            time.sleep(0.1)
        self._increment_blocks(6)
        out = lbrycrds['lbrycrd'].getbalance('test')
        self.assertEqual(SEND_AMOUNT, out)


    def _publish(self, claim_name, claim_amount, key_fee, channel_name=None, test_pub_file_size=1024):
        """
        publish a file randomly created with test_pub_file_size
        """
        test_pub_file_name = claim_name + '.txt'
        test_pub_file_dir = '/src/lbry'
        test_pub_file = os.path.join(test_pub_file_dir, test_pub_file_name)
        expected_download_file = os.path.join('/data/Downloads/', test_pub_file_name)

        key_fee_address = None
        if key_fee != 0:
            key_fee_address = lbrynets['lbrynet'].wallet_new_address()
            test_metadata["fee"] = {'currency': 'LBC', "address": key_fee_address,
                                    "amount": key_fee}
        elif key_fee == 0 and 'fee' in test_metadata:
            del test_metadata['fee']

        self._generate_test_file('lbrynet', test_pub_file_size, test_pub_file)

        out = lbrynets['lbrynet'].publish({
            'name': claim_name, 'file_path': test_pub_file, 'bid': claim_amount,
            'metadata': test_metadata, 'channel_name': channel_name})

        self.assertTrue('txid' in out)
        self.assertTrue('nout' in out)
        self.assertTrue('claim_id' in out)
        self.assertTrue('tx' in out)
        self.assertTrue('fee' in out)
        publish_txid = out['txid']
        publish_nout = out['nout']
        claim_id = out['claim_id']
        self._is_txid(publish_txid)
        self.assertTrue(isinstance(publish_nout, int))

        self.assertTrue(wait_for_lbrynet_sync('lbrycrd', out['txid']))
        self._increment_blocks(6)
        out = {'publish_txid': publish_txid, 'publish_nout': publish_nout, 'claim_id': claim_id,
               'key_fee_address': key_fee_address,
               'expected_download_file': expected_download_file, 'file_name': test_pub_file_name}
        return out

    # makes sure all key,value present in expected_dict is present
    # and equivalent acutal_dict, return True if so
    def _compare_dict(self, expected_dict, actual_dict):
        for key, val in expected_dict.iteritems():
            if key not in actual_dict:
                return False
            if expected_dict[key] != actual_dict[key]:
                return False
        return True

    # test publishing from lbrynet, and test to see if we can download from dht
    @print_func
    def _test_publish(self, claim_name, claim_amount, key_fee=0):
        publish_out = self._publish(claim_name, claim_amount, key_fee)
        publish_txid = publish_out['publish_txid']
        publish_nout = publish_out['publish_nout']
        claim_id = publish_out['claim_id']
        key_fee_address = publish_out['key_fee_address']
        expected_download_file = publish_out['expected_download_file']
        publish_outpoint = publish_txid + ':' + str(publish_nout)

        balance_before_key_fee = lbrynets['lbrynet'].wallet_balance()

        self._check_claim_state(claim_name, publish_out['publish_txid'],
                                publish_out['publish_nout'], claim_amount)

        # test claim_show function
        def check_claim_show_out(out):
            self.assertEqual(claim_name, out['name'])
            self.assertEqual(publish_txid, out['txid'])
            self.assertEqual(publish_nout, out['nout'])
            self.assertEqual(claim_amount, out['amount'])

        out = lbrynets['lbrynet'].claim_show({'txid':publish_txid, 'nout':publish_nout})
        check_claim_show_out(out)
        out = lbrynets['lbrynet'].claim_show({'claim_id':claim_id})
        check_claim_show_out(out)
        sd_hash = out['value']['stream']['source']['source']

        # test claim_list_mine function
        out = lbrynets['lbrynet'].claim_list_mine()
        found = False
        for claim in out:
            if (claim['name'] == claim_name
               and claim['amount'] == claim_amount
               and claim['txid'] == publish_txid
               and claim['nout'] == publish_nout):
                found = True
        self.assertTrue(found)

        # test claim_list function
        out = lbrynets['lbrynet'].claim_list({'name': claim_name})
        self.assertTrue('last_takeover_height' in out)
        self.assertTrue('supports_without_claims' in out)
        self.assertEqual(0, len(out['supports_without_claims']))
        self.assertTrue('claims' in out)
        self.assertEqual(1, len(out['claims']))
        self.assertEqual(publish_txid, out['claims'][0]['txid'])
        self.assertEqual(publish_nout, out['claims'][0]['nout'])
        self.assertEqual(claim_amount, out['claims'][0]['amount'])

        expected_metadata = {
            'license': test_metadata['license'],
            # 'ver':test_metadata['ver'],
            'language': test_metadata['language'],
            'author': test_metadata['author'],
            'title': test_metadata['title'],
            # 'sources':{'lbry_sd_hash':sd_hash},
            'nsfw': test_metadata['nsfw'],
            # 'content_type':'text/plain',
            'description': test_metadata['description']
        }
        if key_fee != 0:
            expected_metadata['fee'] = {'currency': 'LBC', 'address': key_fee_address,
                                        'amount': key_fee, 'version': '_0_0_1'}
        out = lbrynets['lbrynet'].resolve_name({'name': claim_name})
        metadata = out['claim']['value']['stream']['metadata']
        # TODO: need to compare entire claim_dict here
        self.assertTrue(self._compare_dict(expected_metadata, metadata))

        # TODO:need to check stream hash, points paid, written_bytes,
        # completed, stopped
        expected_file_info = {
            'download_directory': '/data/Downloads',
            'name': claim_name,
            'download_path': publish_out['expected_download_file'],
            'file_name': publish_out['file_name'],
            'sd_hash': sd_hash,
            'suggested_file_name': publish_out['file_name'],
            'outpoint': publish_outpoint,
            'stream_name': publish_out['file_name'],
            'claim_id': claim_id,
        }

        # test download of own file
        out = lbrynets['lbrynet'].get({'uri': claim_name})
        self.assertTrue(self._compare_dict(expected_file_info, out))
        self.assertTrue(
            self._compare_dict(expected_metadata, out['metadata']['stream']['metadata']))

        # check file is under file_list
        out = lbrynets['lbrynet'].file_list()
        found_file = False
        for f in out:
            if self._compare_dict(expected_file_info, f):
                found_file = True
        self.assertTrue(found_file)

        # check file_list filtering works
        out = lbrynets['lbrynet'].file_list({'name': claim_name})
        self.assertEqual(1, len(out))
        self.assertTrue(self._compare_dict(expected_file_info, out[0]))
        self.assertTrue(
            self._compare_dict(expected_metadata, out[0]['metadata']['stream']['metadata']))

        out = lbrynets['lbrynet'].file_list({'sd_hash': sd_hash})
        self.assertEqual(1, len(out))
        self.assertTrue(self._compare_dict(expected_file_info, out[0]))
        self.assertTrue(
            self._compare_dict(expected_metadata, out[0]['metadata']['stream']['metadata']))

        out = lbrynets['lbrynet'].file_list({'file_name': publish_out['file_name']})
        self.assertEqual(1, len(out))
        self.assertTrue(self._compare_dict(expected_file_info, out[0]))
        self.assertTrue(
            self._compare_dict(expected_metadata, out[0]['metadata']['stream']['metadata']))

        # check that we can get its blob
        out = lbrynets['lbrynet'].blob_list({'sd_hash': sd_hash})
        self.assertEqual(1, len(out))
        blob_hash = out[0]

        # test download of own descriptor
        # TODO: no longer works after 10.4
        """
        out = lbrynets['lbrynet'].blob_get({'blob_hash':sd_hash,'encoding':'json'})
        print out

        self.assertTrue('blobs' in out)
        self.assertEqual(2, len(out['blobs']))
        self.assertEqual(blob_hash, out['blobs'][0]['blob_hash'])
        self.assertTrue('key' in out)
        self.assertTrue('stream_hash' in out)
        self.assertTrue('stream_name' in out)
        self.assertTrue('stream_type' in out)
        self.assertTrue('suggested_file_name' in out)
        """

        # check reflector to see if it has hashes
        out = lbrynets['reflector'].blob_list()
        self.assertTrue(sd_hash in out)
        self.assertTrue(blob_hash in out)

        # test to see if we can get peers from the dht with the hash
        out = lbrynets['dht'].peer_list({'blob_hash': sd_hash})
        self.assertEqual(2, len(out))

        # test to see if we can download from dht
        if key_fee != 0:
            # send key fee (plus additional amount to pay for tx fee) to dht if necessary
            self._send_from_lbrycrd(key_fee + 1, lbrynets['dht'])

        dht_balance_before_get = lbrynets['dht'].wallet_balance()
        out = lbrynets['dht'].get({'uri': claim_name})
        self.assertTrue(self._compare_dict(expected_file_info, out))

        # wait for download to finish
        DOWNLOAD_TIMEOUT = 30
        start_time = time.time()
        while 1:
            out = lbrynets['dht'].file_list({'sd_hash': sd_hash})
            if out[0]['completed']:
                break
            if time.time() - start_time > DOWNLOAD_TIMEOUT:
                self.fail("Download failed to finish in time")
            time.sleep(1)

        # check to see if dht has the downloaded hashes
        out = lbrynets['dht'].blob_list()
        self.assertTrue(sd_hash in out)
        self.assertTrue(blob_hash in out)

        # check if dht has the file
        self.assertTrue(self._check_has_file('dht', publish_out['expected_download_file']))

        # check sha1sum of files are equivalent
        dht_sha1sum = self._get_sha1sum_of_file('dht', publish_out['expected_download_file'])
        lbrynet_sha1sum = self._get_sha1sum_of_file('lbrynet',
                                                    publish_out['expected_download_file'])
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

        # delete blobs and file
        out = lbrynets['dht'].file_delete({'sd_hash': sd_hash, 'delete_from_download_dir': True})
        self.assertEqual(True, out)
        self.assertFalse(self._check_has_file('dht', publish_out['expected_download_file']))
        out = lbrynets['dht'].file_list()
        self.assertEqual(0, len(out))

    @print_func
    def _test_update(self, claim_name='updatetest', claim_amount=1, update_amount=2, key_fee=0):
        # publish
        publish_out = self._publish(claim_name, claim_amount, key_fee)
        self._check_claim_state(claim_name, publish_out['publish_txid'],
                                publish_out['publish_nout'], claim_amount)

        #  download published file from dht
        out = lbrynets['dht'].get({'uri': claim_name})

        # update
        update_out = self._publish(claim_name, update_amount, key_fee)
        self._check_claim_state(claim_name, update_out['publish_txid'], update_out['publish_nout'],
                                update_amount)

        # check file_list
        out = lbrynets['lbrynet'].file_list({'name': claim_name})
        self.assertEqual(2, len(out))

    @print_func
    def _test_abandon(self, claim_name='abandontest', claim_amount=1, key_fee=0):
        # TODO: should check download and redownload from DHT here

        # publish
        publish_out = self._publish(claim_name, claim_amount, key_fee)

        # abandon
        out = lbrynets['lbrynet'].claim_abandon({'claim_id': publish_out['claim_id']})
        self.assertTrue('txid' in out)
        self.assertTrue('fee' in out)
        self.assertTrue('tx' in out)

        self.assertTrue(wait_for_lbrynet_sync('lbrycrd', out['txid']))
        self._increment_blocks(6)

        # check claimtrie state
        self._check_unclaimed(claim_name)

    @print_func
    def _test_support(self, claim_name='supporttest', claim_amount=1, key_fee=0, support_amount=1):
        # publish
        publish_out = self._publish(claim_name, claim_amount, key_fee)

        # support
        out = lbrynets['lbrynet'].claim_new_support(
            {'name': claim_name, 'claim_id': publish_out['claim_id'], 'amount': support_amount})
        self.assertTrue('txid' in out)
        support_txid = out['txid']
        self.assertTrue('nout' in out)
        support_nout = out['nout']
        self.assertTrue('fee' in out)

        support_txid = out['txid']
        support_nout = out['nout']

        self.assertTrue(wait_for_lbrynet_sync('lbrycrd', out['txid']))
        self._increment_blocks(6)

        out = lbrynets['lbrynet'].claim_list({'name':claim_name})
        self.assertTrue('supports' in out['claims'][0])
        self.assertEqual(1, len(out['claims'][0]['supports']))
        self.assertEqual(out['claims'][0]['supports'][0]['amount'], support_amount)
        self.assertEqual(out['claims'][0]['supports'][0]['txid'], support_txid)
        self.assertEqual(out['claims'][0]['supports'][0]['nout'], support_nout)
        self.assertEqual(out['claims'][0]['effective_amount'], claim_amount + support_amount)

        out = lbrycrds['lbrycrd'].getvalueforname(claim_name)
        self.assertEqual(out['effective amount'], (claim_amount+support_amount)*100000000)

        def test_resolve_out(uri, out):
            self.assertTrue('supports' in out[uri]['claim'])
            self.assertEqual(1, len(out[uri]['claim']['supports']))
            self.assertEqual({'txid':support_txid,'nout':support_nout,'amount':support_amount},out[uri]['claim']['supports'][0])
            self.assertEqual(claim_amount + support_amount, out[uri]['claim']['effective_amount'])

        uri = claim_name
        out = lbrynets['lbrynet'].resolve({'uri':uri, 'force':True})
        test_resolve_out(uri, out)

        uri = claim_name+':1'
        out = lbrynets['lbrynet'].resolve({'uri':uri, 'force':True})
        test_resolve_out(uri, out)

        # test abandon of support
        out = lbrynets['lbrynet'].claim_abandon({'txid':support_txid, 'nout':support_nout})
        self.assertTrue('txid' in out)
        self.assertTrue('fee' in out)

    @print_func
    def _test_channels(self, channel_name='@testchannel', channel_claim_amount=0.5,
                       claim_name='channelclaim', claim_amount=1):

        out = lbrynets['lbrynet'].channel_list_mine()
        self.assertEqual(0, len(out))

        # claim channel
        channel_out = lbrynets['lbrynet'].channel_new(
            {'channel_name': channel_name, 'amount': channel_claim_amount})
        self.assertTrue('tx' in channel_out)
        self.assertTrue('txid' in channel_out)
        self.assertTrue('nout' in channel_out)
        self.assertTrue('claim_id' in channel_out)

        self.assertTrue(wait_for_lbrynet_sync('lbrycrd', channel_out['txid']))
        self._increment_blocks(6)

        self._check_claim_state(channel_name, channel_out['txid'], channel_out['nout'],
                                channel_claim_amount)

        out = lbrynets['lbrynet'].channel_list_mine()
        self.assertEqual(1, len(out))
        self.assertEqual(channel_out['txid'], out[0]['txid'])
        self.assertEqual(channel_out['nout'], out[0]['nout'])
        self.assertEqual(channel_name, out[0]['name'])
        self.assertEqual(channel_claim_amount, out[0]['amount'])
        self.assertTrue('address' in out[0])
        #TODO: this needs to be corrected
        #self.assertEqual(6, out[0]['confirmations'])
        self.assertFalse(out[0]['is_pending'])
        self.assertFalse(out[0]['is_spent'])
        self.assertFalse(out[0]['expired'])

        # publish with channel
        publish_out = self._publish(claim_name, claim_amount, key_fee=0, channel_name=channel_name)

        def check_claim_with_channel(out, uri):
            claim = out[uri]['claim']
            self.assertEqual(claim['txid'], publish_out['publish_txid'])
            self.assertEqual(claim['nout'], publish_out['publish_nout'])
            self.assertEqual(claim['name'], claim_name)
            self.assertTrue(claim['signature_is_valid'])
            self.assertEqual(claim['channel_name'],channel_name)

            certificate = out[uri]['certificate']
            self.assertEqual(certificate['txid'], channel_out['txid'])
            self.assertEqual(certificate['nout'], channel_out['nout'])
            self.assertEqual(certificate['name'], channel_name)
            self.assertEqual(certificate['claim_sequence'], 1)

        out = lbrynets['lbrynet'].resolve({'uri': claim_name, 'force': True})
        check_claim_with_channel(out,claim_name)
        uri_claim = channel_name + '/' + claim_name
        out = lbrynets['lbrynet'].resolve({'uri': uri_claim, 'force': True})
        check_claim_with_channel(out, uri_claim)

        # TODO: this doesn't work yet due to bug
        #uri_claim = channel_name + '#' + publish_out['claim_id']
        #out = lbrynets['lbrynet'].resolve({'uri': uri_claim, 'force':True})
        #check_claim_with_channel(out, uri_claim)


        def check_channel_resolve(out, uri):
            claim = out[uri]['certificate']
            self.assertEqual(claim['txid'], channel_out['txid'])
            self.assertEqual(claim['nout'], channel_out['nout'])
            self.assertEqual(claim['name'], channel_name)


        uri = channel_name
        out = lbrynets['lbrynet'].resolve({'uri': uri, 'force': True})
        check_channel_resolve(out, uri)

        uri = channel_name + ':1'
        out = lbrynets['lbrynet'].resolve({'uri': uri, 'force': True})
        check_channel_resolve(out, uri)



    @print_func
    def _test_invalid_claims(self):
        """
        test various invalid ways of making claims here
        """

        # test insuficient funds when publishing
        balance = lbrynets['lbrynet'].wallet_balance()
        with self.assertRaises(HTTPError):
            self._publish('insufficientpublish', balance+1, key_fee=0)

    @print_func
    def _test_uri(self):
        # check unclaimed URI's
        out = lbrynets['lbrynet'].resolve({"uri": "somethingunclaimed:1", 'force': True})
        self._check_lbrynet_unclaimed_resolve(out)
        out = lbrynets['lbrynet'].resolve({"uri": "@somethingunclaimed", 'force': True})
        self._check_lbrynet_unclaimed_resolve(out)
        out = lbrynets['lbrynet'].resolve({"uri": "@somethingunclaimed/unclaimed", 'force': True})
        self._check_lbrynet_unclaimed_resolve(out)



    @print_func
    def _test_batch_cmds(self):
        out = lbrynets['lbrynet'].resolve({"uris": ['testname', 'testname2']})
        self.assertEqual(len(out), 2)

        out = lbrynets['lbrynet'].resolve({"uris": ['someunclaimedname1', 'someunclaimedname2']})
        self.assertEqual(len(out), 2)


        # test pagination

    @print_func
    def _test_misc(self):
        # test claim_show output on non existing claims
        out = lbrynets['lbrynet'].claim_show({'claim_id':'be1bf9f2296660dd8cbbac03219d01205e2e36ab'})
        self.assertTrue('error' in out)

        out = lbrynets['lbrynet'].claim_show({'txid':'b67ce42c182a57b9becc408d2baf3ae7a504a8a97c0dc27d884d3e4d62a72473', 'nout':0})
        self.assertTrue('error' in out)


        # test claim_list on non existing name
        out = lbrynets['lbrynet'].claim_list({'name':'someunclaimedname'})
        self.assertEqual(0, len(out['claims']))
        self.assertEqual(0, len(out['supports_without_claims']))


if __name__ == '__main__':
    unittest.main()
