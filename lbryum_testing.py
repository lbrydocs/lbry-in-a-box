import unittest
from test_utils import *
from socket import error
import time

from lbryschema.claim import ClaimDict

# wait till txid appears on lbrycrd
def wait_for_lbrynet_sync(instance, txid=None,timeout=90):
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

# increment num_blocks block on lbrycrd and wait for lbrynets
# and lbryum to be in sync, return True if sycned within timeout,
# False otherwise
def increment_blocks(num_blocks, instance='lbrycrd', timeout=60):
    out = lbrycrds[instance].generate(num_blocks)
    assert(len(out) == num_blocks)
    for blockhash in out:
        assert len(blockhash) == 64

    # wait till all lbrynet instances in sync with the
    # tip of the blockchain
    best_block_hash = lbrycrds[instance].getbestblockhash()
    start_time = time.time()
    while time.time() - start_time < timeout:
        # wait till all lbrycrd in sync
        if all([lbrycrd.getbestblockhash() == best_block_hash for lbrycrd in lbrycrds.values()]):
            # wait till lbryum blockhash is best
            if call_lbryum('getbestblockhash') == best_block_hash:
                return True
        time.sleep(1)
    return False


TEST_METADATA ={u'version': u'_0_0_1', u'claimType': u'streamType', u'stream': {u'source': {u'source': u'cc04fd50bc58c9393945307eafa7e7981212bf2ded47b198deca5a9d4a4f3d3f42420b5b91dbc642df5d3a54518c213b', u'version': u'_0_0_1', u'contentType': u'text/plain', u'sourceType': u'lbry_sd_hash'}, u'version': u'_0_0_1', u'metadata': {u'description': u'test_description', u'license': u'NASA', u'author': u'test_author', u'title': u'test_title', u'language': u'en', u'version': u'_0_1_0', u'nsfw': False, u'licenseUrl': u'', u'preview': u'', u'thumbnail': u''}}}


class LbryumTest(unittest.TestCase):

    def setup(self):
        docker_compose_build()
        time.sleep(10)# TODO: without this calls to lbrycrd fails... 
        start_time = time.time()
        while 1:
            try:
                count1 = lbrycrds['lbrycrd'].getblockcount()
                count2 = lbrycrds['lbryum-server'].getblockcount()
                lbryum_status = call_lbryum('getnetworkstatus')
            except Exception as e:
                print e
            else:
                if (count1 == NUM_INITIAL_BLOCKS_GENERATED and count2 == NUM_INITIAL_BLOCKS_GENERATED
                    and lbryum_status['local_height'] == NUM_INITIAL_BLOCKS_GENERATED):
                    break
            if time.time() - start_time > 90:
                self.fail('failed to initialize:{}'.format(e))
            time.sleep(1)

    def test_lbryum(self):
        self.setup()
        self._send_to_lbryum()

        self._test_claim()
        self._test_claim_reorg()
        self._test_claim_abandon_reorg()
        self._test_update_reorg()
        self._test_claim_signed_reorg()
        self._test_abandon_signed_reorg()

        self._test_invalid_update()

    def _test_claim(self):
        # make claim here, empty claimtrie causes problem in lbryum proofs
        claim_out = call_lbryum('claim','testclaim','test',0.01,
                            None,True,None,None,None,True,True,True)
        self.assertTrue('txid' in claim_out)
        self.assertTrue(wait_for_lbrynet_sync('lbryum-server',claim_out['txid']))
        increment_blocks(1)

    def _test_abandon_signed_reorg(self):
        # test abandon of a signed claim being reorged out
        def _pre_setup_func():
            # make certificate
            self.cert_out = call_lbryum('claimcertificate', '@channel2', 0.01)

            self.assertTrue('txid' in self.cert_out)
            self.assertTrue(wait_for_lbrynet_sync('lbryum-server',self.cert_out['txid']))
            self.assertTrue(increment_blocks(6, 'lbryum-server'))

            # make claim
            metadata = TEST_METADATA

            claim_val = ClaimDict.load_dict(metadata).serialized.encode('hex')
            self.claim_out = call_lbryum('claim','abandonsigned',claim_val,0.01, self.cert_out['claim_id'])
            self.assertTrue('txid' in self.claim_out)
            self.assertTrue(wait_for_lbrynet_sync('lbryum-server',self.claim_out['txid']))

            self.assertTrue(increment_blocks(6, 'lbryum-server'))

        def _setup_reorg_func():
            #abandon claim
            self.abandon_out = call_lbryum('abandon',self.claim_out['claim_id'])
            self.assertTrue('txid' in self.abandon_out)
            self.assertTrue(wait_for_lbrynet_sync('lbryum-server',self.abandon_out['txid']))

        def _mid_reorg_func():
            out = call_lbryum('getclaimsinchannel', '@channel2')
            self.assertEqual(0, len(out))

            out = call_lbrycrd_lbryum_server('getvalueforname','abandonsigned')
            self.assertEqual({},out)
            out = call_lbryum('getvalueforname','abandonedsigned')
            self.assertTrue('error' in out)
            self.assertEqual(out['error'],'name is not claimed')

        def _post_reorg_func():
            # check claim
            out = call_lbrycrd_lbryum_server('getvalueforname','abandonsigned')
            self.assertEqual(out['txid'],self.claim_out['txid'])
            self.assertEqual(out['n'],self.claim_out['nout'])

            out = call_lbryum('getvalueforname','abandonsigned')
            self.assertEqual(out['txid'], self.claim_out['txid'])
            self.assertEqual(out['nout'], self.claim_out['nout'])

            out = call_lbryum('getclaimsinchannel', '@channel2')
            self.assertEqual(1, len(out))
            self.assertEqual(self.claim_out['txid'], out[0]['txid'])
            self.assertEqual(self.claim_out['nout'], out[0]['nout'])


        self._test_reorg(_pre_setup_func,_setup_reorg_func,_mid_reorg_func,_post_reorg_func)


    def _test_claim_signed_reorg(self):
        # test a signed claim being reorged out
        def _pre_setup_func():
            self.cert_out = call_lbryum('claimcertificate', '@channel', 0.01)
            self.assertTrue('txid' in self.cert_out)
            self.assertTrue(wait_for_lbrynet_sync('lbryum-server',self.cert_out['txid']))
            self.assertTrue(increment_blocks(6, 'lbryum-server'))


        def _setup_reorg_func():
            metadata = TEST_METADATA
            claim_val = ClaimDict.load_dict(metadata).serialized.encode('hex')
            self.claim_out = call_lbryum('claim','signedclaimreorgtest',claim_val,0.01, self.cert_out['claim_id'])
            self.assertTrue('txid' in self.claim_out)
            self.assertTrue(wait_for_lbrynet_sync('lbryum-server',self.claim_out['txid']))

        def _mid_reorg_func():
            # check claim
            out = call_lbrycrd_lbryum_server('getvalueforname','signedclaimreorgtest')
            self.assertEqual(out['txid'],self.claim_out['txid'])
            self.assertEqual(out['n'],self.claim_out['nout'])
            out = call_lbryum('getvalueforname','signedclaimreorgtest')
            self.assertEqual(out['txid'], self.claim_out['txid'])
            self.assertEqual(out['nout'], self.claim_out['nout'])

            out = call_lbryum('getclaimsinchannel', '@channel')
            self.assertEqual(1, len(out))
            self.assertEqual(self.claim_out['txid'], out[0]['txid'])
            self.assertEqual(self.claim_out['nout'], out[0]['nout'])

        def _post_reorg_func():
            out = call_lbryum('getclaimsinchannel', '@channel')
            self.assertEqual(0, len(out))

            out = call_lbrycrd_lbryum_server('getvalueforname','signedclaimreorgtest')
            self.assertEqual({},out)
            out = call_lbryum('getvalueforname','signedclaimreorgtest')
            self.assertTrue('error' in out)
            self.assertEqual(out['error'],'name is not claimed')


        self._test_reorg(_pre_setup_func,_setup_reorg_func,_mid_reorg_func,_post_reorg_func)


    def _test_claim_abandon_reorg(self):
        def _pre_setup_func():
            #make original claim to be abandoned
            self.claim_out = call_lbryum('claim','abandonreorgtest','originalclaim',0.01,
                                None,True,None,None,None,True,True,True)
            self.assertTrue('txid' in self.claim_out)
            self.assertTrue(wait_for_lbrynet_sync('lbryum-server',self.claim_out['txid']))
            self.assertTrue(increment_blocks(6, 'lbryum-server'))

            out = lbrycrds['lbryum-server'].getvalueforname('abandonreorgtest')
            self.assertEqual(out['txid'], self.claim_out['txid'])
            self.assertEqual(out['n'], self.claim_out['nout'])

            out =  lbrycrds['lbrycrd'].getvalueforname('abandonreorgtest')
            self.assertEqual(out['txid'], self.claim_out['txid'])
            self.assertEqual(out['n'], self.claim_out['nout'])


        def _setup_reorg_func():
            abandon_out = call_lbryum('abandon',self.claim_out['claim_id'])
            self.assertTrue('txid' in abandon_out)
            self.assertTrue(wait_for_lbrynet_sync('lbryum-server',abandon_out['txid']))

        def _mid_reorg_func():
            # check claim
            out = call_lbrycrd_lbryum_server('getvalueforname','abandonreorgtest')
            self.assertEqual({},out)
            out = call_lbryum('getvalueforname','abandonreorgtest')
            self.assertTrue('error' in out)
            self.assertEqual(out['error'],'name is not claimed')

        def _post_reorg_func():
            out = lbrycrds['lbryum-server'].getvalueforname('abandonreorgtest')
            self.assertEqual(out['txid'], self.claim_out['txid'])
            self.assertEqual(out['n'], self.claim_out['nout'])

            out =  lbrycrds['lbrycrd'].getvalueforname('abandonreorgtest')
            self.assertEqual(out['txid'], self.claim_out['txid'])
            self.assertEqual(out['n'], self.claim_out['nout'])

        self._test_reorg(_pre_setup_func,_setup_reorg_func,_mid_reorg_func,_post_reorg_func)

    def _test_update_reorg(self):
        def _pre_setup_func():
            #make original claim to be updated
            self.claim_out = call_lbryum('claim','updatereorgtest','originalclaim',0.01,
                                None,True,None,None,None,True,True,True)
            self.assertTrue('txid' in self.claim_out)
            self.assertTrue(wait_for_lbrynet_sync('lbryum-server',self.claim_out['txid']))
            self.assertTrue(increment_blocks(6, 'lbryum-server'))

            out = lbrycrds['lbryum-server'].getvalueforname('updatereorgtest')
            self.assertEqual(out['txid'], self.claim_out['txid'])
            self.assertEqual(out['n'], self.claim_out['nout'])

            out =  lbrycrds['lbrycrd'].getvalueforname('updatereorgtest')
            self.assertEqual(out['txid'], self.claim_out['txid'])
            self.assertEqual(out['n'], self.claim_out['nout'])

        def _setup_reorg_func():
            # make update that will be reorged out
            self.update_out = call_lbryum('update','updatereorgtest','updateclaim',0.01, None,
                    self.claim_out['claim_id'], self.claim_out['txid'], self.claim_out['nout'],True,None,
                    None, None, True, True)
            self.assertTrue('txid' in self.update_out)
            self.assertTrue('txid' in self.claim_out)
            self.assertTrue(wait_for_lbrynet_sync('lbryum-server',self.update_out['txid']))

        def _mid_reorg_func():
            # This should be the update
            out = call_lbrycrd_lbryum_server('getvalueforname','updatereorgtest')
            self.assertEqual(self.update_out['claim_id'], out['claimId'])
            self.assertEqual('updateclaim', out['value'])
            self.assertEqual(self.update_out['txid'], out['txid'])
            self.assertEqual(self.update_out['nout'], out['n'])

            out = call_lbryum('getvalueforname','updatereorgtest')
            self.assertEqual(self.update_out['claim_id'], out['claim_id'])
            self.assertEqual(self.update_out['txid'], out['txid'])
            self.assertEqual(self.update_out['nout'], out['nout'])

        def _post_reorg_func():
            # Update will be reorged out, this should be the claim
            out = call_lbrycrd_lbryum_server('getvalueforname','updatereorgtest')
            self.assertEqual(self.claim_out['txid'],out['txid'])
            self.assertEqual(self.claim_out['nout'],out['n'])

            out = call_lbryum('getvalueforname','updatereorgtest')
            self.assertEqual(self.claim_out['txid'],out['txid'])
            self.assertEqual(self.claim_out['nout'],out['nout'])

        self._test_reorg(_pre_setup_func,_setup_reorg_func,_mid_reorg_func,_post_reorg_func)

    def _test_claim_reorg(self):
        def _pre_setup_func():
            pass
        def _setup_reorg_func():
            claim_out = call_lbryum('claim','claimreorgtest','test',0.01,
                                None,True,None,None,None,True,True,True)
            self.assertTrue('txid' in claim_out)
            self.assertTrue(wait_for_lbrynet_sync('lbryum-server',claim_out['txid']))
            self.claim_id = claim_out['claim_id']

        def _pre_reorg_func():
            # check claim
            out = call_lbrycrd_lbryum_server('getvalueforname','claimreorgtest')
            self.assertEqual(self.claim_id, out['claimId'])
            out = call_lbryum('getvalueforname','claimreorgtest')
            self.assertEqual(self.claim_id, out['claim_id'])

        def _post_reorg_func():
            # check claim
            out = call_lbrycrd_lbryum_server('getvalueforname','claimreorgtest')
            self.assertEqual({},out)
            out = call_lbryum('getvalueforname','claimreorgtest')

        self._test_reorg(_pre_setup_func,_setup_reorg_func,_pre_reorg_func,_post_reorg_func)


    def _send_to_lbryum(self):
        address = call_lbryum('getunusedaddress')
        out = lbrycrds['lbrycrd'].sendtoaddress(address,10)
        increment_blocks(6)

    def _test_reorg(self, pre_setup_func, setup_func, mid_reorg_func, post_reorg_func, reorg_blocks=3):
        """ This function helps tests Reorgs """

        pre_setup_func()
        # make sure lbrycrdd instances are connected
        #lbrycrds['lbryum-server'].addnode(lbrycrd_addr,'onetry')
        #lbrycrds['lbrycrd'].addnode(lbryum_server_lbrycrd_addr,'onetry')


        # disconnect lbrycrdd instances,
        # TODO: disconnectnode fails occasionally, sometimes its already disconnected here
        peerinfo = lbrycrds['lbryum-server'].getpeerinfo()
        lbrycrd_addr = peerinfo[0]['addr']
        lbrycrds['lbryum-server'].disconnectnode(lbrycrd_addr)
        peerinfo = lbrycrds['lbrycrd'].getpeerinfo()
        lbryum_server_lbrycrd_addr = peerinfo[0]['addr']
        lbrycrds['lbrycrd'].disconnectnode(lbryum_server_lbrycrd_addr)
        lbrycrds['lbryum-server'].setban('0.0.0.0'+'/0','add')
        lbryum_server_lbrycrd_mask = lbryum_server_lbrycrd_addr.split(':')[0]+'/0'
        lbrycrds['lbrycrd'].setban(lbryum_server_lbrycrd_mask,'add')

        # wait till they are disconnected
        start_time = time.time()
        REORG_SYNC_TIMEOUT = 120
        while 1:
            peerinfo = lbrycrds['lbryum-server'].getpeerinfo()
            peerinfo2 = lbrycrds['lbrycrd'].getpeerinfo()
            if len(peerinfo) == 0 and len(peerinfo2) == 0:
                break
            elif time.time() - start_time > REORG_SYNC_TIMEOUT:
                self.fail('failed to disconnect within timeout')


        setup_func()
        height = lbrycrds['lbryum-server'].getblockcount()

        # generate block on lbryum server
        call_lbrycrd_lbryum_server('generate', reorg_blocks)
        best_block_hash = call_lbrycrd_lbryum_server('getbestblockhash')
        self.assertEqual(height+reorg_blocks, call_lbrycrd_lbryum_server('getblockcount'))
        start_time = time.time()
        while 1:
            # wait till lbryum blockhash is best
            if call_lbryum('getbestblockhash') == best_block_hash:
                break
            elif time.time() - start_time > REORG_SYNC_TIMEOUT:
                self.fail('failed to sync within timeout')
            time.sleep(1)

        mid_reorg_func()

        # generate 1 more blocks on lbrycrdd and connect , this will
        # trigger a reorg
        call_lbrycrd('generate', reorg_blocks+1)
        block_hash = call_lbrycrd('getbestblockhash')
        self.assertEqual(height+reorg_blocks+1, call_lbrycrd('getblockcount'))
        call_lbrycrd_lbryum_server('setban','0.0.0.0/0','remove');
        call_lbrycrd('setban',lbryum_server_lbrycrd_mask,'remove');

        # unban and connect
        lbrycrds['lbryum-server'].addnode(lbrycrd_addr,'onetry')
        lbrycrds['lbrycrd'].addnode(lbryum_server_lbrycrd_addr,'onetry')

        # wait till blockhash is is equal, reorg has been finished
        start_time = time.time()
        while 1:
            # wait till lbryum blockhash is best
            if (lbrycrds['lbryum-server'].getbestblockhash() == block_hash and call_lbryum('getbestblockhash') == block_hash):
                break
            elif time.time() - start_time > REORG_SYNC_TIMEOUT:
                self.fail('failed to sync within timeout')
            time.sleep(1)

        post_reorg_func()


    # this test makes sure that invalid updates do not make it in the claim trie
    # on lbryum server
    def _test_invalid_update(self):
        # send balance to lbryum instance
        address = call_lbryum('getunusedaddress')
        out = call_lbrycrd('sendtoaddress',address,1)
        increment_blocks(6)

        claim_out = call_lbryum('claim','invalidupdate','test',0.01,
                            None,True,None,None,None,True,True,True)
        wait_for_lbrynet_sync('lbrycrd',claim_out['txid'])
        increment_blocks(6)

        claim_out_2 = call_lbryum('claim','unrelatedupdate','test',0.01,
                            None,True,None,None,None,True,True,True)
        wait_for_lbrynet_sync('lbrycrd',claim_out_2['txid'])
        increment_blocks(6)

        # this update is invalid because it spends the wrong outpoint
        update_out = call_lbryum('update','invalidupdate','test2',0.1, None, claim_out['claim_id'], claim_out_2['txid'], claim_out_2['nout'],True,None,
            None, None, True, True)
        wait_for_lbrynet_sync('lbrycrd',update_out['txid'])
        increment_blocks(6)

        out=call_lbryum('getclaimbyid',claim_out['claim_id'])
        self.assertEqual(out['txid'],claim_out['txid'])
        self.assertEqual(out['nout'],claim_out['nout'])

        # this update is valid
        update_out = call_lbryum('update','invalidupdate','test2',0.1, None, claim_out['claim_id'], claim_out['txid'], claim_out['nout'],True,None,
            None, None, True, True)
        wait_for_lbrynet_sync('lbrycrd',update_out['txid'])
        increment_blocks(6)

        out=call_lbryum('getclaimbyid',claim_out['claim_id'])
        self.assertEqual(out['txid'],update_out['txid'])
        self.assertEqual(out['nout'],update_out['nout'])

        # this update is invalid because it specifies the wrong name, will be an abandon
        update_out = call_lbryum('update','invalidupdateXX','test2',0.1, None, claim_out['claim_id'], update_out['txid'], update_out['nout'],True,None,
            None, None, True, True)
        wait_for_lbrynet_sync('lbrycrd',update_out['txid'])
        increment_blocks(6)

        out=call_lbryum('getclaimbyid',claim_out['claim_id'])
        self.assertEqual({},out)

if __name__ == '__main__':

    unittest.main()


