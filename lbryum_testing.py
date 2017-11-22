import unittest
import time

from test_utils import *

from lbryschema.claim import ClaimDict


# increment num_blocks block on lbrycrd and wait for lbrynets
# and lbryum to be in sync, return True if sycned within timeout,
# False otherwise
def increment_blocks(num_blocks, instance='lbrycrd', timeout=60):
    out = lbrycrds[instance].generate(num_blocks)
    assert (len(out) == num_blocks)
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


TEST_METADATA = {u'version': u'_0_0_1', u'claimType': u'streamType', u'stream': {u'source': {
    u'source': u'cc04fd50bc58c9393945307eafa7e7981212bf2ded47b198deca5a9d4a4f3d3f42420b5b91dbc642df5d3a54518c213b',
    u'version': u'_0_0_1', u'contentType': u'text/plain', u'sourceType': u'lbry_sd_hash'},
    u'version': u'_0_0_1',
    u'metadata': {
        u'description': u'test_description',
        u'license': u'NASA',
        u'author': u'test_author',
        u'title': u'test_title',
        u'language': u'en',
        u'version': u'_0_1_0',
        u'nsfw': False,
        u'licenseUrl': u'',
        u'preview': u'',
        u'thumbnail': u''}}}

DEFAULT_CLAIMVAL = ClaimDict.load_dict(TEST_METADATA).serialized.encode('hex')


def call_lbryum_claim(claim_name, claim_val, amount):
    certificate_id = None
    broadcast = True
    claim_addr = None
    tx_fee = None
    change_addr = None
    raw = True
    skip_validate_schema = True
    skip_update_check = True

    return call_lbryum('claim', claim_name, claim_val, amount,
                       certificate_id, broadcast, claim_addr, tx_fee, change_addr,
                       raw, skip_validate_schema, skip_update_check)

def call_lbryum_getnameclaims(txid=None, nout=None):
    raw = True
    include_abandoned = False
    include_supports = True
    txid = txid
    nout = nout
    claim_id = None
    skip_validate_signatures = True
    return call_lbryum('getnameclaims', raw, include_abandoned, include_supports, txid, nout,
                       claim_id, skip_validate_signatures)


class LbryumTest(unittest.TestCase):
    def setup(self):
        docker_compose_build()
        time.sleep(10)  # TODO: without this calls to lbrycrd fails...
        start_time = time.time()
        while 1:
            try:
                count1 = lbrycrds['lbrycrd'].getblockcount()
                count2 = lbrycrds['lbryum-server'].getblockcount()
                lbryum_status = call_lbryum('getnetworkstatus')
            except Exception as e:
                print e
            else:
                if (count1 == NUM_INITIAL_BLOCKS_GENERATED
                   and count2 == NUM_INITIAL_BLOCKS_GENERATED
                   and lbryum_status['local_height'] == NUM_INITIAL_BLOCKS_GENERATED):
                    break
            if time.time() - start_time > 90:
                self.fail('failed to initialize:{}'.format(e))
            time.sleep(1)

    def _send_to_lbryum(self):
        address = call_lbryum('getunusedaddress')
        out = lbrycrds['lbrycrd'].sendtoaddress(address, 20)
        increment_blocks(6)

    def test_lbryum(self):

        self.setup()
        self._send_to_lbryum()

        self._test_claim_and_getvalue()
        self._test_claim_sequence()
        self._test_update_same_block()
        self._test_abandon_same_block()
        self._test_claim_signed_update()

        self._test_claim_reorg()
        self._test_abandon_reorg()
        self._test_update_reorg()
        self._test_claim_signed_reorg()
        self._test_abandon_signed_reorg()

        self._test_update_signed_reorg_unsigned_to_signed()
        self._test_update_signed_reorg_signed_to_unsigned()
        self._test_update_signed_reorg_change_cert()

        self._test_invalid_update()

    @print_func
    def _test_update_same_block(self):

        claim_out = call_lbryum_claim('updatesameblock', 'test', 0.01)
        self.assertTrue('txid' in claim_out)
        self.assertTrue(call_lbryum('waitfortxinwallet', claim_out['txid']))
        # make update
        update_out = call_lbryum('update', 'updatesameblock', 'updateclaim', 0.01, None,
                                 claim_out['claim_id'], claim_out['txid'], claim_out['nout'], True,
                                 None,
                                 None, None, True, True)
        self.assertTrue('txid' in update_out)
        self.assertTrue(call_lbryum('waitfortxinwallet', update_out['txid']))

        increment_blocks(1, 'lbryum-server')
        out = call_lbryum('getclaimbyid', claim_out['claim_id'])
        self.assertEqual(out['txid'], update_out['txid'])
        self.assertEqual(out['nout'], update_out['nout'])

    @print_func
    def _test_abandon_same_block(self):
        claim_out = call_lbryum_claim('abandonsameblock', 'test', 0.01)
        self.assertTrue('txid' in claim_out)
        self.assertTrue(call_lbryum('waitfortxinwallet', claim_out['txid']))

        abandon_out = call_lbryum('abandon', None, claim_out['txid'], claim_out['nout'])
        self.assertTrue('txid' in abandon_out)
        self.assertTrue(call_lbryum('waitfortxinwallet', abandon_out['txid']))

        increment_blocks(1, 'lbryum-server')
        out = call_lbryum('getclaimbyid', claim_out['claim_id'])
        self.assertEqual({}, out)

    @print_func
    def _test_claim_and_getvalue(self):
        # make claim here, empty claimtrie causes problem in lbryum proofs
        claim_out = call_lbryum_claim('testclaim', 'testval', 0.01)
        self.assertTrue('txid' in claim_out)
        self.assertTrue(call_lbryum('waitfortxinwallet', claim_out['txid']))
        increment_blocks(1, 'lbryum-server')

        # test claim that doesn't exist
        out = call_lbryum('getvalueforname', 'someclaimnoexistxxx')
        self.assertTrue('error' in out)
        self.assertEqual(out['error'], "name is not claimed")

        out = call_lbryum('getvalueforname', 'testclaim', True)
        self.assertEqual(out['value'].decode('hex'), 'testval')

    @print_func
    def _test_claim_sequence(self):
        # test handling of claim sequence numbers here

        # make 2 claims
        claim_1_out = call_lbryum_claim('testsequenceclaim', 'test', 0.01)
        self.assertTrue('txid' in claim_1_out)
        self.assertTrue(call_lbryum('waitfortxinwallet', claim_1_out['txid']))
        increment_blocks(1, 'lbryum-server')

        out = call_lbryum('getnthclaimforname', 'testsequenceclaim', 1)
        self.assertEqual(claim_1_out['txid'], out['txid'])
        self.assertEqual(claim_1_out['nout'], out['nout'])

        claim_2_out = call_lbryum_claim('testsequenceclaim', 'test', 0.01)
        self.assertTrue('txid' in claim_2_out)
        self.assertTrue(call_lbryum('waitfortxinwallet', claim_2_out['txid']))
        increment_blocks(1, 'lbryum-server')

        out = call_lbryum('getnthclaimforname', 'testsequenceclaim', 2)
        self.assertEqual(claim_2_out['txid'], out['txid'])
        self.assertEqual(claim_2_out['nout'], out['nout'])

        out = call_lbryum('getnthclaimforname', 'testsequenceclaim', 1)
        self.assertEqual(claim_1_out['txid'], out['txid'])
        self.assertEqual(claim_1_out['nout'], out['nout'])

        # Test update does not affect sequence
        update_1_out = call_lbryum('update', 'testsequenceclaim', 'updateclaim', 0.01, None,
                                   claim_1_out['claim_id'], claim_1_out['txid'],
                                   claim_1_out['nout'], True, None,
                                   None, None, True, True)
        self.assertTrue('txid' in update_1_out)
        self.assertTrue(call_lbryum('waitfortxinwallet', update_1_out['txid']))
        increment_blocks(1, 'lbryum-server')

        out = call_lbryum('getnthclaimforname', 'testsequenceclaim', 2)
        self.assertEqual(claim_2_out['txid'], out['txid'])
        self.assertEqual(claim_2_out['nout'], out['nout'])

        out = call_lbryum('getnthclaimforname', 'testsequenceclaim', 1)
        self.assertEqual(update_1_out['txid'], out['txid'])
        self.assertEqual(update_1_out['nout'], out['nout'])

        # Test abandon of claim 1 (claim 2 will become claim 1)
        abandon_out = call_lbryum('abandon', claim_1_out['claim_id'])
        self.assertTrue('txid' in abandon_out)
        self.assertTrue(call_lbryum('waitfortxinwallet', abandon_out['txid']))
        increment_blocks(1, 'lbryum-server')

        out = call_lbryum('getnthclaimforname', 'testsequenceclaim', 1)
        self.assertEqual(claim_2_out['txid'], out['txid'])
        self.assertEqual(claim_2_out['nout'], out['nout'])

        out = call_lbryum('getnthclaimforname', 'testsequenceclaim', 2)
        self.assertEqual({}, out)

        # Test abandon of claim 2 (no more claims)
        abandon_out = call_lbryum('abandon', claim_2_out['claim_id'])
        self.assertTrue('txid' in abandon_out)
        self.assertTrue(call_lbryum('waitfortxinwallet', abandon_out['txid']))
        increment_blocks(1, 'lbryum-server')

        out = call_lbryum('getnthclaimforname', 'testsequenceclaim', 1)
        self.assertEqual({}, out)

        out = call_lbryum('getnthclaimforname', 'testsequenceclaim', 2)
        self.assertEqual({}, out)

    @print_func
    def _test_claim_signed_update(self):
        # make certificates
        cert_out = call_lbryum('claimcertificate', '@claimsignupdatechannel', 0.01)
        self.assertTrue('txid' in cert_out)
        self.assertTrue(call_lbryum('waitfortxinwallet', cert_out['txid']))
        self.assertTrue(increment_blocks(1, 'lbryum-server'))

        cert_out_2 = call_lbryum('claimcertificate', '@claimsignupdatechannel2', 0.01)
        self.assertTrue('txid' in cert_out_2)
        self.assertTrue(call_lbryum('waitfortxinwallet', cert_out_2['txid']))
        self.assertTrue(increment_blocks(1, 'lbryum-server'))

        # make a claim with out signing
        claim_out = call_lbryum_claim('claimsignupdate', DEFAULT_CLAIMVAL, 0.01)
        self.assertTrue('txid' in claim_out)
        self.assertTrue(call_lbryum('waitfortxinwallet', claim_out['txid']))
        self.assertTrue(increment_blocks(6, 'lbryum-server'))

        # update the claim with signing
        update_out = call_lbryum('update', 'claimsignupdate', DEFAULT_CLAIMVAL, 0.01,
                                 cert_out['claim_id'], claim_out['claim_id'], claim_out['txid'],
                                 claim_out['nout'])

        self.assertTrue('txid' in update_out)
        self.assertTrue(call_lbryum('waitfortxinwallet', update_out['txid']))
        increment_blocks(6, 'lbryum-server')

        out = call_lbryum('getclaimsinchannel', '@claimsignupdatechannel')
        self.assertEqual(1, len(out))
        self.assertEqual(update_out['txid'], out[0]['txid'])
        self.assertEqual(update_out['nout'], out[0]['nout'])

        out = call_lbryum('getclaimsinchannel', '@claimsignupdatechannel2')
        self.assertEqual(0, len(out))

        # update it, with same certificate
        update_out = call_lbryum('update', 'claimsignupdate', DEFAULT_CLAIMVAL, 0.01,
                                 cert_out['claim_id'], claim_out['claim_id'], update_out['txid'],
                                 update_out['nout'])

        self.assertTrue('txid' in update_out)
        self.assertTrue(call_lbryum('waitfortxinwallet', update_out['txid']))
        increment_blocks(6, 'lbryum-server')

        out = call_lbryum('getclaimsinchannel', '@claimsignupdatechannel')
        self.assertEqual(1, len(out))
        self.assertEqual(update_out['txid'], out[0]['txid'])
        self.assertEqual(update_out['nout'], out[0]['nout'])

        out = call_lbryum('getclaimsinchannel', '@claimsignupdatechannel2')
        self.assertEqual(0, len(out))

        # update it, with different certficates
        update_out = call_lbryum('update', 'claimsignupdate', DEFAULT_CLAIMVAL, 0.01,
                                 cert_out_2['claim_id'], claim_out['claim_id'], update_out['txid'],
                                 update_out['nout'])
        self.assertTrue('txid' in update_out)
        self.assertTrue(call_lbryum('waitfortxinwallet', update_out['txid']))
        increment_blocks(6, 'lbryum-server')

        out = call_lbryum('getclaimsinchannel', '@claimsignupdatechannel')
        self.assertEqual(0, len(out))

        out = call_lbryum('getclaimsinchannel', '@claimsignupdatechannel2')
        self.assertEqual(1, len(out))
        self.assertEqual(update_out['txid'], out[0]['txid'])
        self.assertEqual(update_out['nout'], out[0]['nout'])

    @print_func
    def _test_abandon_signed_reorg(self):
        # test abandon of a signed claim being reorged out
        def _pre_setup_func():
            # make certificate
            self.cert_out = call_lbryum('claimcertificate', '@channel2', 0.01)
            self.assertTrue('txid' in self.cert_out)
            self.assertTrue(call_lbryum('waitfortxinwallet', self.cert_out['txid']))
            self.assertTrue(increment_blocks(6, 'lbryum-server'))

            # make claim
            self.claim_out = call_lbryum('claim', 'abandonsigned', DEFAULT_CLAIMVAL, 0.01,
                                         self.cert_out['claim_id'])
            self.assertTrue('txid' in self.claim_out)
            self.assertTrue(call_lbryum('waitfortxinwallet', self.claim_out['txid']))
            self.assertTrue(increment_blocks(6, 'lbryum-server'))

        def _setup_reorg_func():
            # abandon claim
            self.abandon_out = call_lbryum('abandon', self.claim_out['claim_id'])
            self.assertTrue('txid' in self.abandon_out)
            self.assertTrue(call_lbryum('waitfortxinwallet', self.abandon_out['txid']))

        def _mid_reorg_func():
            out = call_lbryum('getclaimsinchannel', '@channel2')
            self.assertEqual(0, len(out))

            out = lbrycrds['lbryum-server'].getvalueforname('abandonsigned')
            self.assertEqual({}, out)
            out = call_lbryum('getvalueforname', 'abandonedsigned')
            self.assertTrue('error' in out)
            self.assertEqual(out['error'], 'name is not claimed')

        def _post_reorg_func():
            # check claim
            out = lbrycrds['lbryum-server'].getvalueforname('abandonsigned')
            self.assertEqual(out['txid'], self.claim_out['txid'])
            self.assertEqual(out['n'], self.claim_out['nout'])

            out = call_lbryum('getvalueforname', 'abandonsigned')
            self.assertEqual(out['txid'], self.claim_out['txid'])
            self.assertEqual(out['nout'], self.claim_out['nout'])

            out = call_lbryum('getclaimsinchannel', '@channel2')
            self.assertEqual(1, len(out))
            self.assertEqual(self.claim_out['txid'], out[0]['txid'])
            self.assertEqual(self.claim_out['nout'], out[0]['nout'])

        self._test_reorg(_pre_setup_func, _setup_reorg_func, _mid_reorg_func, _post_reorg_func)

    @print_func
    def _test_update_signed_reorg_change_cert(self):
        # test reorg of an update where it changes certificate of a claim

        def _pre_setup_func():
            # make certificate claims
            self.cert_out = call_lbryum('claimcertificate', '@updatereorgcert', 0.01)
            self.assertTrue('txid' in self.cert_out)
            self.assertTrue(call_lbryum('waitfortxinwallet', self.cert_out['txid']))
            self.assertTrue(increment_blocks(6, 'lbryum-server'))

            self.cert_out_2 = call_lbryum('claimcertificate', '@updatereorgcert2', 0.01)
            self.assertTrue('txid' in self.cert_out_2)
            self.assertTrue(call_lbryum('waitfortxinwallet', self.cert_out_2['txid']))
            self.assertTrue(increment_blocks(6, 'lbryum-server'))

            # make signed claim
            self.claim_signed_out = call_lbryum('claim', 'updatereorgcert', DEFAULT_CLAIMVAL, 0.01,
                                                self.cert_out['claim_id'])
            self.assertTrue('txid' in self.claim_signed_out)
            self.assertTrue(call_lbryum('waitfortxinwallet', self.claim_signed_out['txid']))
            self.assertTrue(increment_blocks(6, 'lbryum-server'))

        def _setup_reorg_func():
            # update cert to different cert
            self.update_out = call_lbryum('update', 'updatereorgcert', DEFAULT_CLAIMVAL, 0.01,
                                          self.cert_out_2['claim_id'],
                                          self.claim_signed_out['claim_id'],
                                          self.claim_signed_out['txid'],
                                          self.claim_signed_out['nout'])
            self.assertTrue('txid' in self.update_out)
            self.assertTrue(call_lbryum('waitfortxinwallet', self.update_out['txid']))

        def _mid_reorg_func():
            # check claim
            out = call_lbryum('getclaimsinchannel', '@updatereorgcert')
            self.assertEqual(0, len(out))
            out = call_lbryum('getclaimsinchannel', '@updatereorgcert2')
            self.assertEqual(1, len(out))
            self.assertEqual(self.update_out['txid'], out[0]['txid'])
            self.assertEqual(self.update_out['nout'], out[0]['nout'])

        def _post_reorg_func():
            out = call_lbryum('getclaimsinchannel', '@updatereorgcert')
            self.assertEqual(1, len(out))
            self.assertEqual(self.claim_signed_out['txid'], out[0]['txid'])
            self.assertEqual(self.claim_signed_out['nout'], out[0]['nout'])
            out = call_lbryum('getclaimsinchannel', '@updatereorgcert2')
            self.assertEqual(0, len(out))

        self._test_reorg(_pre_setup_func, _setup_reorg_func, _mid_reorg_func, _post_reorg_func)

    @print_func
    def _test_update_signed_reorg_signed_to_unsigned(self):
        # test reorg of an update where it changes a signed claim to unsigned 
        def _pre_setup_func():
            # make certificate claims
            self.cert_out = call_lbryum('claimcertificate', '@reorgtest22channel', 0.01)
            self.assertTrue('txid' in self.cert_out)
            self.assertTrue(call_lbryum('waitfortxinwallet', self.cert_out['txid']))
            self.assertTrue(increment_blocks(6, 'lbryum-server'))

            # make signed claim
            self.claim_signed_out = call_lbryum('claim', 'reorgtest22', DEFAULT_CLAIMVAL, 0.01,
                                                self.cert_out['claim_id'])
            self.assertTrue('txid' in self.claim_signed_out)
            self.assertTrue(call_lbryum('waitfortxinwallet', self.claim_signed_out['txid']))
            self.assertTrue(increment_blocks(6, 'lbryum-server'))

        def _setup_reorg_func():
            # update signed claim to unsigned
            self.update_out = call_lbryum('update', 'reorgtest22', DEFAULT_CLAIMVAL, 0.01, None,
                                          self.claim_signed_out['claim_id'],
                                          self.claim_signed_out['txid'],
                                          self.claim_signed_out['nout'])
            self.assertTrue('txid' in self.update_out)
            self.assertTrue(call_lbryum('waitfortxinwallet', self.update_out['txid']))

        def _mid_reorg_func():
            # check claim
            out = call_lbryum('getclaimsinchannel', '@reorgtest22channel')
            self.assertEqual(0, len(out))

        def _post_reorg_func():
            out = call_lbryum('getclaimsinchannel', '@reorgtest22channel')
            self.assertEqual(1, len(out))
            self.assertEqual(self.claim_signed_out['txid'], out[0]['txid'])
            self.assertEqual(self.claim_signed_out['nout'], out[0]['nout'])

        self._test_reorg(_pre_setup_func, _setup_reorg_func, _mid_reorg_func, _post_reorg_func)

    @print_func
    def _test_update_signed_reorg_unsigned_to_signed(self):
        # test reorg of an update where it changes an unsigned claim to signed
        def _pre_setup_func():
            # make certificate claims
            self.cert_out = call_lbryum('claimcertificate', '@reorgupdatetest3channel', 0.01)
            self.assertTrue('txid' in self.cert_out)
            self.assertTrue(call_lbryum('waitfortxinwallet', self.cert_out['txid']))
            self.assertTrue(increment_blocks(6, 'lbryum-server'))

            # make unsigned claim
            self.claim_unsigned_out = call_lbryum('claim', 'reorgupdatetest3', DEFAULT_CLAIMVAL,
                                                  0.01)
            self.assertTrue('txid' in self.claim_unsigned_out)
            self.assertTrue(call_lbryum('waitfortxinwallet', self.claim_unsigned_out['txid']))
            self.assertTrue(increment_blocks(6, 'lbryum-server'))

        def _setup_reorg_func():
            # update unsigned claim to sgined
            self.signed_update_out = call_lbryum('update', 'reorgupdatetest3', DEFAULT_CLAIMVAL,
                                                 0.01,
                                                 self.cert_out['claim_id'],
                                                 self.claim_unsigned_out['claim_id'],
                                                 self.claim_unsigned_out['txid'],
                                                 self.claim_unsigned_out['nout'])
            self.assertTrue('txid' in self.signed_update_out)
            self.assertTrue(call_lbryum('waitfortxinwallet', self.signed_update_out['txid']))

        def _mid_reorg_func():
            # check claim

            out = call_lbryum('getclaimsinchannel', '@reorgupdatetest3channel')
            self.assertEqual(1, len(out))
            self.assertEqual(self.signed_update_out['txid'], out[0]['txid'])
            self.assertEqual(self.signed_update_out['nout'], out[0]['nout'])

        def _post_reorg_func():
            out = call_lbryum('getclaimsinchannel', '@reorgupdatetest3channel')
            self.assertEqual(0, len(out))

        self._test_reorg(_pre_setup_func, _setup_reorg_func, _mid_reorg_func, _post_reorg_func)

    @print_func
    def _test_claim_signed_reorg(self):
        # test a signed claim being reorged out
        def _pre_setup_func():
            self.cert_out = call_lbryum('claimcertificate', '@channel', 0.01)
            self.assertTrue('txid' in self.cert_out)
            self.assertTrue(call_lbryum('waitfortxinwallet', self.cert_out['txid']))
            self.assertTrue(increment_blocks(6, 'lbryum-server'))

        def _setup_reorg_func():
            self.claim_out = call_lbryum('claim', 'signedclaimreorgtest', DEFAULT_CLAIMVAL, 0.01,
                                         self.cert_out['claim_id'])
            self.assertTrue('txid' in self.claim_out)
            self.assertTrue(call_lbryum('waitfortxinwallet', self.claim_out['txid']))

        def _mid_reorg_func():
            # check claim
            out = lbrycrds['lbryum-server'].getvalueforname('signedclaimreorgtest')
            self.assertEqual(out['txid'], self.claim_out['txid'])
            self.assertEqual(out['n'], self.claim_out['nout'])
            out = call_lbryum('getvalueforname', 'signedclaimreorgtest')
            self.assertEqual(out['txid'], self.claim_out['txid'])
            self.assertEqual(out['nout'], self.claim_out['nout'])

            out = call_lbryum('getclaimsinchannel', '@channel')
            self.assertEqual(1, len(out))
            self.assertEqual(self.claim_out['txid'], out[0]['txid'])
            self.assertEqual(self.claim_out['nout'], out[0]['nout'])

        def _post_reorg_func():
            out = call_lbryum('getclaimsinchannel', '@channel')
            self.assertEqual(0, len(out))

            out = lbrycrds['lbryum-server'].getvalueforname('signedclaimreorgtest')
            self.assertEqual({}, out)
            out = call_lbryum('getvalueforname', 'signedclaimreorgtest')
            self.assertTrue('error' in out)
            self.assertEqual(out['error'], 'name is not claimed')

        self._test_reorg(_pre_setup_func, _setup_reorg_func, _mid_reorg_func, _post_reorg_func)

    @print_func
    def _test_abandon_reorg(self):
        def _pre_setup_func():
            # make original claim to be abandoned
            self.claim_out = call_lbryum('claim', 'abandonreorgtest', 'originalclaim', 0.01,
                                         None, True, None, None, None, True, True, True)
            self.assertTrue('txid' in self.claim_out)
            self.assertTrue(call_lbryum('waitfortxinwallet', self.claim_out['txid']))
            self.assertTrue(increment_blocks(6, 'lbryum-server'))

            out = lbrycrds['lbryum-server'].getvalueforname('abandonreorgtest')
            self.assertEqual(out['txid'], self.claim_out['txid'])
            self.assertEqual(out['n'], self.claim_out['nout'])

            out = lbrycrds['lbrycrd'].getvalueforname('abandonreorgtest')
            self.assertEqual(out['txid'], self.claim_out['txid'])
            self.assertEqual(out['n'], self.claim_out['nout'])

        def _setup_reorg_func():
            abandon_out = call_lbryum('abandon', self.claim_out['claim_id'])
            self.assertTrue('txid' in abandon_out)
            self.assertTrue(call_lbryum('waitfortxinwallet', abandon_out['txid']))

        def _mid_reorg_func():
            # check claim
            out = lbrycrds['lbryum-server'].getvalueforname('abandonreorgtest')
            self.assertEqual({}, out)
            out = call_lbryum('getvalueforname', 'abandonreorgtest')
            self.assertTrue('error' in out)
            self.assertEqual(out['error'], 'name is not claimed')

        def _post_reorg_func():
            out = lbrycrds['lbryum-server'].getvalueforname('abandonreorgtest')
            self.assertEqual(out['txid'], self.claim_out['txid'])
            self.assertEqual(out['n'], self.claim_out['nout'])

            out = lbrycrds['lbrycrd'].getvalueforname('abandonreorgtest')
            self.assertEqual(out['txid'], self.claim_out['txid'])
            self.assertEqual(out['n'], self.claim_out['nout'])

            out = call_lbryum('getclaimbyid', self.claim_out['claim_id'])
            self.assertEqual(out['txid'], self.claim_out['txid'])
            self.assertEqual(out['nout'], self.claim_out['nout'])

        self._test_reorg(_pre_setup_func, _setup_reorg_func, _mid_reorg_func, _post_reorg_func)

    @print_func
    def _test_update_reorg(self):
        def _pre_setup_func():
            # make original claim to be updated
            self.claim_out = call_lbryum('claim', 'updatereorgtest', 'originalclaim', 0.01,
                                         None, True, None, None, None, True, True, True)
            self.assertTrue('txid' in self.claim_out)
            self.assertTrue(call_lbryum('waitfortxinwallet', self.claim_out['txid']))
            self.assertTrue(increment_blocks(6, 'lbryum-server'))

            out = lbrycrds['lbryum-server'].getvalueforname('updatereorgtest')
            self.assertEqual(out['txid'], self.claim_out['txid'])
            self.assertEqual(out['n'], self.claim_out['nout'])

            out = lbrycrds['lbrycrd'].getvalueforname('updatereorgtest')
            self.assertEqual(out['txid'], self.claim_out['txid'])
            self.assertEqual(out['n'], self.claim_out['nout'])

        def _setup_reorg_func():
            # make update that will be reorged out
            self.update_out = call_lbryum('update', 'updatereorgtest', 'updateclaim', 0.01, None,
                                          self.claim_out['claim_id'], self.claim_out['txid'],
                                          self.claim_out['nout'], True, None,
                                          None, None, True, True)
            self.assertTrue('txid' in self.update_out)
            self.assertTrue('txid' in self.claim_out)
            self.assertTrue(call_lbryum('waitfortxinwallet', self.update_out['txid']))

        def _mid_reorg_func():
            # This should be the update
            out = lbrycrds['lbryum-server'].getvalueforname('updatereorgtest')
            self.assertEqual(self.update_out['claim_id'], out['claimId'])
            self.assertEqual('updateclaim', out['value'])
            self.assertEqual(self.update_out['txid'], out['txid'])
            self.assertEqual(self.update_out['nout'], out['n'])

            out = call_lbryum('getvalueforname', 'updatereorgtest')
            self.assertEqual(self.update_out['claim_id'], out['claim_id'])
            self.assertEqual(self.update_out['txid'], out['txid'])
            self.assertEqual(self.update_out['nout'], out['nout'])

        def _post_reorg_func():
            # Update will be reorged out, this should be the claim
            out = lbrycrds['lbryum-server'].getvalueforname('updatereorgtest')
            self.assertEqual(self.claim_out['txid'], out['txid'])
            self.assertEqual(self.claim_out['nout'], out['n'])

            out = call_lbryum('getvalueforname', 'updatereorgtest')
            self.assertEqual(self.claim_out['txid'], out['txid'])
            self.assertEqual(self.claim_out['nout'], out['nout'])

        self._test_reorg(_pre_setup_func, _setup_reorg_func, _mid_reorg_func, _post_reorg_func)

    @print_func
    def _test_claim_reorg(self):
        def _pre_setup_func():
            pass

        def _setup_reorg_func():
            claim_out = call_lbryum('claim', 'claimreorgtest', 'test', 0.01,
                                    None, True, None, None, None, True, True, True)
            self.assertTrue('txid' in claim_out)
            self.assertTrue(call_lbryum('waitfortxinwallet', claim_out['txid']))
            self.claim_id = claim_out['claim_id']

        def _pre_reorg_func():
            # check claim
            out = lbrycrds['lbryum-server'].getvalueforname('claimreorgtest')
            self.assertEqual(self.claim_id, out['claimId'])
            out = call_lbryum('getvalueforname', 'claimreorgtest')
            self.assertEqual(self.claim_id, out['claim_id'])

        def _post_reorg_func():
            # check claim
            out = lbrycrds['lbryum-server'].getvalueforname('claimreorgtest')
            self.assertEqual({}, out)
            out = call_lbryum('getvalueforname', 'claimreorgtest')

        self._test_reorg(_pre_setup_func, _setup_reorg_func, _pre_reorg_func, _post_reorg_func)

    def _test_reorg(self, pre_setup_func, setup_func, mid_reorg_func, post_reorg_func,
                    reorg_blocks=3):
        """ This function helps tests Reorgs """

        pre_setup_func()

        # disconnect lbrycrdd instances,
        lbryum_server_peerinfo = lbrycrds['lbryum-server'].getpeerinfo()
        lbrycrd_addr = lbryum_server_peerinfo[0]['addr']
        lbrycrd_peerinfo = lbrycrds['lbrycrd'].getpeerinfo()
        lbryum_server_lbrycrd_addr = lbrycrd_peerinfo[0]['addr']

        lbrycrds['lbryum-server'].disconnectnode(lbrycrd_addr)
        # this fails sometimes, already disconnected?
        lbrycrds['lbrycrd'].disconnectnode(lbryum_server_lbrycrd_addr)
        lbrycrds['lbryum-server'].setban('0.0.0.0' + '/0', 'add')
        lbryum_server_lbrycrd_mask = lbryum_server_lbrycrd_addr.split(':')[0] + '/0'
        lbrycrds['lbrycrd'].setban(lbryum_server_lbrycrd_mask, 'add')

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
        lbrycrds['lbryum-server'].generate(reorg_blocks)
        best_block_hash = lbrycrds['lbryum-server'].getbestblockhash()
        self.assertEqual(height + reorg_blocks, lbrycrds['lbryum-server'].getblockcount())
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
        lbrycrds['lbrycrd'].generate(reorg_blocks + 1)
        block_hash = lbrycrds['lbrycrd'].getbestblockhash()
        self.assertEqual(height + reorg_blocks + 1, lbrycrds['lbrycrd'].getblockcount())
        lbrycrds['lbryum-server'].setban('0.0.0.0/0', 'remove')
        lbrycrds['lbrycrd'].setban(lbryum_server_lbrycrd_mask, 'remove')

        # unban and connect
        lbrycrds['lbryum-server'].addnode(lbrycrd_addr, 'onetry')
        lbrycrds['lbrycrd'].addnode(lbryum_server_lbrycrd_addr, 'onetry')

        # wait till blockhash is is equal, reorg has been finished
        start_time = time.time()
        while 1:
            # wait till lbryum blockhash is best
            if (lbrycrds['lbryum-server'].getbestblockhash() == block_hash and call_lbryum(
                    'getbestblockhash') == block_hash):
                break
            elif time.time() - start_time > REORG_SYNC_TIMEOUT:
                self.fail('failed to sync within timeout')
            time.sleep(1)

        post_reorg_func()

    @print_func
    def _test_invalid_update(self):
        """
        this test makes sure that invalid updates do not make it in the claim trie
        on lbryum server
        """
        # send balance to lbryum instance
        address = call_lbryum('getunusedaddress')
        out = lbrycrds['lbrycrd'].sendtoaddress(address, 1)
        increment_blocks(6)

        claim_out = call_lbryum('claim', 'invalidupdate', 'test', 0.01,
                                None, True, None, None, None, True, True, True)
        wait_for_lbrynet_sync('lbrycrd', claim_out['txid'])
        increment_blocks(6)

        claim_out_2 = call_lbryum('claim', 'unrelatedupdate', 'test', 0.01,
                                  None, True, None, None, None, True, True, True)
        wait_for_lbrynet_sync('lbrycrd', claim_out_2['txid'])
        increment_blocks(6)

        # this update is invalid because it spends the wrong outpoint
        update_out = call_lbryum('update', 'invalidupdate', 'test2', 0.1, None,
                                 claim_out['claim_id'], claim_out_2['txid'], claim_out_2['nout'],
                                 True, None,
                                 None, None, True, True)
        wait_for_lbrynet_sync('lbrycrd', update_out['txid'])
        increment_blocks(6)

        out = call_lbryum('getclaimbyid', claim_out['claim_id'])
        self.assertEqual(out['txid'], claim_out['txid'])
        self.assertEqual(out['nout'], claim_out['nout'])

        # this update is valid
        update_out = call_lbryum('update', 'invalidupdate', 'test2', 0.1, None,
                                 claim_out['claim_id'], claim_out['txid'], claim_out['nout'], True,
                                 None,
                                 None, None, True, True)
        wait_for_lbrynet_sync('lbrycrd', update_out['txid'])
        increment_blocks(6)

        out = call_lbryum('getclaimbyid', claim_out['claim_id'])
        self.assertEqual(out['txid'], update_out['txid'])
        self.assertEqual(out['nout'], update_out['nout'])

        # this update is invalid because it specifies the wrong name, will be an abandon
        update_out = call_lbryum('update', 'invalidupdateXX', 'test2', 0.1, None,
                                 claim_out['claim_id'], update_out['txid'], update_out['nout'],
                                 True, None,
                                 None, None, True, True)
        wait_for_lbrynet_sync('lbrycrd', update_out['txid'])
        increment_blocks(6)

        out = call_lbryum('getclaimbyid', claim_out['claim_id'])
        self.assertEqual({}, out)

 
if __name__ == '__main__':
    unittest.main()
