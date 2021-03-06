# Copyright (c) 2014, 2015, Oracle and/or its affiliates. All rights reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
"""Unit tests for Oracle's ZFSSA Cinder volume driver."""

import json

import mock
from oslo_utils import units
import six

from cinder import context
from cinder import exception
from cinder import test
from cinder.tests.unit import fake_utils
from cinder.volume import configuration as conf
from cinder.volume.drivers.zfssa import restclient as client
from cinder.volume.drivers.zfssa import webdavclient
from cinder.volume.drivers.zfssa import zfssaiscsi as iscsi
from cinder.volume.drivers.zfssa import zfssanfs
from cinder.volume.drivers.zfssa import zfssarest as rest


nfs_logbias = 'latency'
nfs_compression = 'off'


class FakeResponse(object):
    def __init__(self, statuscode, data='data'):
        self.status = statuscode
        self.data = data


class FakeSSL(object):
    def _create_unverified_context(self):
        return 'fakecontext'


class TestZFSSAISCSIDriver(test.TestCase):

    test_vol = {
        'name': 'cindervol',
        'size': 1,
        'id': 1,
        'provider_location': 'fake_location 1 2',
        'provider_auth': 'fake_auth user pass',
    }

    test_snap = {
        'name': 'cindersnap',
        'volume_name': test_vol['name']
    }

    test_vol_snap = {
        'name': 'cindersnapvol',
        'size': test_vol['size']
    }

    def __init__(self, method):
        super(TestZFSSAISCSIDriver, self).__init__(method)

    @mock.patch.object(iscsi, 'factory_zfssa')
    def setUp(self, _factory_zfssa):
        super(TestZFSSAISCSIDriver, self).setUp()
        self._create_fake_config()
        _factory_zfssa.return_value = mock.MagicMock(spec=rest.ZFSSAApi)
        iscsi.ZFSSAISCSIDriver._execute = fake_utils.fake_execute
        self.drv = iscsi.ZFSSAISCSIDriver(configuration=self.configuration)
        self.drv.do_setup({})

    def _create_fake_config(self):
        self.configuration = mock.Mock(spec=conf.Configuration)
        self.configuration.san_ip = '1.1.1.1'
        self.configuration.san_login = 'user'
        self.configuration.san_password = 'passwd'
        self.configuration.zfssa_pool = 'pool'
        self.configuration.zfssa_project = 'project'
        self.configuration.zfssa_lun_volblocksize = '8k'
        self.configuration.zfssa_lun_sparse = 'false'
        self.configuration.zfssa_lun_logbias = 'latency'
        self.configuration.zfssa_lun_compression = 'off'
        self.configuration.zfssa_initiator_group = 'test-init-grp1'
        self.configuration.zfssa_initiator = \
            'iqn.1-0.org.deb:01:d7, iqn.1-0.org.deb:01:d9'
        self.configuration.zfssa_initiator_user = ''
        self.configuration.zfssa_initiator_password = ''
        self.configuration.zfssa_initiator_config = "{'test-init-grp1':[{'iqn':\
            'iqn.1-0.org.deb:01:d7','user':'','password':''}],'test-init-grp\
            2':[{'iqn':'iqn.1-0.org.deb:01:d9','user':'','password':''}]}"
        self.configuration.zfssa_target_group = 'test-target-grp1'
        self.configuration.zfssa_target_user = ''
        self.configuration.zfssa_target_password = ''
        self.configuration.zfssa_target_portal = '1.1.1.1:3260'
        self.configuration.zfssa_target_interfaces = 'e1000g0'
        self.configuration.zfssa_rest_timeout = 60
        self.configuration.volume_backend_name = 'fake_zfssa'
        self.configuration.safe_get = self.fake_safe_get
        self.configuration.zfssa_replication_ip = '1.1.1.1'

    def _util_migrate_volume_exceptions(self):
        self.drv.zfssa.get_lun.return_value = (
            {'targetgroup': 'test-target-grp1'})
        self.drv.zfssa.get_asn.return_value = (
            '9a2b5a0f-e3af-6d14-9578-8825f229dc89')
        self.drv.tgt_zfssa.get_asn.return_value = (
            '9a2b5a0f-e3af-6d14-9578-8825f229dc89')
        targets = {'targets': [{'hostname': '2.2.2.2',
                                'address': '2.2.2.2:216',
                                'label': '2.2.2.2',
                                'asn':
                                '9a2b5a0f-e3af-6d14-9578-8825f229dc89'}]}

        self.drv.zfssa.get_replication_targets.return_value = targets
        self.drv.zfssa.edit_inherit_replication_flag.return_value = {}
        self.drv.zfssa.create_replication_action.return_value = 'action-123'
        self.drv.zfssa.send_repl_update.return_value = True

    def test_migrate_volume(self):
        self._util_migrate_volume_exceptions()

        volume = self.test_vol
        volume.update({'host': 'fake_host',
                       'status': 'available',
                       'name': 'vol-1',
                       'source_volid': self.test_vol['id']})

        loc_info = '2.2.2.2:fake_auth:pool2:project2:test-target-grp1:2.2.2.2'

        host = {'host': 'stack@zfssa_iscsi#fake_zfssa',
                'capabilities': {'vendor_name': 'Oracle',
                                 'storage_protocol': 'iSCSI',
                                 'location_info': loc_info}}
        ctxt = context.get_admin_context()

        # Test the normal case
        result = self.drv.migrate_volume(ctxt, volume, host)
        self.assertEqual((True, None), result)

        # Test when volume status is not available
        volume['status'] = 'in-use'
        result = self.drv.migrate_volume(ctxt, volume, host)
        self.assertEqual((False, None), result)
        volume['status'] = 'available'

        # Test when vendor is not Oracle
        host['capabilities']['vendor_name'] = 'elcarO'
        result = self.drv.migrate_volume(ctxt, volume, host)
        self.assertEqual((False, None), result)
        host['capabilities']['vendor_name'] = 'Oracle'

        # Test when storage protocol is not iSCSI
        host['capabilities']['storage_protocol'] = 'not_iSCSI'
        result = self.drv.migrate_volume(ctxt, volume, host)
        self.assertEqual((False, None), result)
        host['capabilities']['storage_protocol'] = 'iSCSI'

        # Test when location_info is incorrect
        host['capabilities']['location_info'] = ''
        self.assertEqual((False, None), result)
        host['capabilities']['location_info'] = loc_info

        # Test if replication ip and replication target's address dont match
        invalid_loc_info = (
            '2.2.2.2:fake_auth:pool2:project2:test-target-grp1:9.9.9.9')
        host['capabilities']['location_info'] = invalid_loc_info
        result = self.drv.migrate_volume(ctxt, volume, host)
        self.assertEqual((False, None), result)
        host['capabilities']['location_info'] = loc_info

        # Test if no targets are returned
        self.drv.zfssa.get_replication_targets.return_value = {'targets': []}
        result = self.drv.migrate_volume(ctxt, volume, host)
        self.assertEqual((False, None), result)

    def test_migrate_volume_uninherit_exception(self):
        self._util_migrate_volume_exceptions()

        volume = self.test_vol
        volume.update({'host': 'fake_host',
                       'status': 'available',
                       'name': 'vol-1',
                       'source_volid': self.test_vol['id']})

        loc_info = '2.2.2.2:fake_auth:pool2:project2:test-target-grp1:2.2.2.2'

        host = {'host': 'stack@zfssa_iscsi#fake_zfssa',
                'capabilities': {'vendor_name': 'Oracle',
                                 'storage_protocol': 'iSCSI',
                                 'location_info': loc_info}}
        ctxt = context.get_admin_context()

        self.drv.zfssa.edit_inherit_replication_flag.side_effect = (
            exception.VolumeBackendAPIException(data='uniherit ex'))
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.drv.migrate_volume, ctxt, volume, host)

    def test_migrate_volume_create_action_exception(self):
        self._util_migrate_volume_exceptions()

        volume = self.test_vol
        volume.update({'host': 'fake_host',
                       'status': 'available',
                       'name': 'vol-1',
                       'source_volid': self.test_vol['id']})

        loc_info = '2.2.2.2:fake_auth:pool2:project2:test-target-grp1:2.2.2.2'

        host = {'host': 'stack@zfssa_iscsi#fake_zfssa',
                'capabilities': {'vendor_name': 'Oracle',
                                 'storage_protocol': 'iSCSI',
                                 'location_info': loc_info}}
        ctxt = context.get_admin_context()

        self.drv.zfssa.create_replication_action.side_effect = (
            exception.VolumeBackendAPIException(data=
                                                'failed to create action'))
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.drv.migrate_volume, ctxt, volume, host)

    def test_migrate_volume_send_update_exception(self):
        self._util_migrate_volume_exceptions()

        volume = self.test_vol
        volume.update({'host': 'fake_host',
                       'status': 'available',
                       'name': 'vol-1',
                       'source_volid': self.test_vol['id']})

        loc_info = '2.2.2.2:fake_auth:pool2:project2:test-target-grp1:2.2.2.2'

        host = {'host': 'stack@zfssa_iscsi#fake_zfssa',
                'capabilities': {'vendor_name': 'Oracle',
                                 'storage_protocol': 'iSCSI',
                                 'location_info': loc_info}}
        ctxt = context.get_admin_context()

        self.drv.zfssa.send_repl_update.side_effect = (
            exception.VolumeBackendAPIException(data='failed to send update'))
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.drv.migrate_volume, ctxt, volume, host)

    def test_migrate_volume_sever_repl_exception(self):
        self._util_migrate_volume_exceptions()

        volume = self.test_vol
        volume.update({'host': 'fake_host',
                       'status': 'available',
                       'name': 'vol-1',
                       'source_volid': self.test_vol['id']})

        loc_info = '2.2.2.2:fake_auth:pool2:project2:test-target-grp1:2.2.2.2'

        host = {'host': 'stack@zfssa_iscsi#fake_zfssa',
                'capabilities': {'vendor_name': 'Oracle',
                                 'storage_protocol': 'iSCSI',
                                 'location_info': loc_info}}
        ctxt = context.get_admin_context()
        self.drv.tgt_zfssa.sever_replication.side_effect = (
            exception.VolumeBackendAPIException(data=
                                                'failed to sever replication'))
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.drv.migrate_volume, ctxt, volume, host)

    def test_create_delete_volume(self):
        self.drv.zfssa.get_lun.return_value = {'guid':
                                               '00000000000000000000000000000',
                                               'number': 0,
                                               'initiatorgroup': 'default',
                                               'size': 1,
                                               'nodestroy': False}
        lcfg = self.configuration
        self.drv.create_volume(self.test_vol)
        self.drv.zfssa.create_lun.assert_called_once_with(
            lcfg.zfssa_pool,
            lcfg.zfssa_project,
            self.test_vol['name'],
            six.text_type(self.test_vol['size']) + 'g',
            lcfg.zfssa_target_group,
            mock.ANY)
        self.drv.delete_volume(self.test_vol)
        self.drv.zfssa.get_lun.assert_called_once_with(lcfg.zfssa_pool,
                                                       lcfg.zfssa_project,
                                                       self.test_vol['name'])
        self.drv.zfssa.delete_lun.assert_called_once_with(
            pool=lcfg.zfssa_pool,
            project=lcfg.zfssa_project,
            lun=self.test_vol['name'])

    def test_create_delete_snapshot(self):
        self.drv.zfssa.has_clones.return_value = False
        lcfg = self.configuration
        self.drv.create_snapshot(self.test_snap)
        self.drv.zfssa.create_snapshot.assert_called_once_with(
            lcfg.zfssa_pool,
            lcfg.zfssa_project,
            self.test_snap['volume_name'],
            self.test_snap['name'])
        self.drv.delete_snapshot(self.test_snap)
        self.drv.zfssa.delete_snapshot.assert_called_once_with(
            lcfg.zfssa_pool,
            lcfg.zfssa_project,
            self.test_snap['volume_name'],
            self.test_snap['name'])

    @mock.patch.object(iscsi.ZFSSAISCSIDriver, '_verify_clone_size')
    def test_create_volume_from_snapshot(self, _verify_clone_size):
        self.drv._verify_clone_size.return_value = True
        lcfg = self.configuration
        self.drv.create_snapshot(self.test_snap)
        self.drv.zfssa.create_snapshot.assert_called_once_with(
            lcfg.zfssa_pool,
            lcfg.zfssa_project,
            self.test_snap['volume_name'],
            self.test_snap['name'])
        self.drv.create_volume_from_snapshot(self.test_vol_snap,
                                             self.test_snap)
        self.drv._verify_clone_size.assert_called_once_with(
            self.test_snap,
            self.test_vol_snap['size'] * units.Gi)
        self.drv.zfssa.clone_snapshot.assert_called_once_with(
            lcfg.zfssa_pool,
            lcfg.zfssa_project,
            self.test_snap['volume_name'],
            self.test_snap['name'],
            self.test_vol_snap['name'])

    @mock.patch.object(iscsi.ZFSSAISCSIDriver, '_get_provider_info')
    def test_volume_attach_detach(self, _get_provider_info):
        lcfg = self.configuration
        test_target_iqn = 'iqn.1986-03.com.sun:02:00000-aaaa-bbbb-cccc-ddddd'
        stub_val = {'provider_location':
                    '%s %s 0' % (lcfg.zfssa_target_portal, test_target_iqn)}
        self.drv._get_provider_info.return_value = stub_val

        connector = dict(initiator='iqn.1-0.org.deb:01:d7')
        props = self.drv.initialize_connection(self.test_vol, connector)
        self.drv._get_provider_info.assert_called_once_with(self.test_vol)
        self.assertEqual('iscsi', props['driver_volume_type'])
        self.assertEqual(self.test_vol['id'], props['data']['volume_id'])
        self.assertEqual(lcfg.zfssa_target_portal,
                         props['data']['target_portal'])
        self.assertEqual(test_target_iqn, props['data']['target_iqn'])
        self.assertEqual('0', props['data']['target_lun'])
        self.assertFalse(props['data']['target_discovered'])

        self.drv.terminate_connection(self.test_vol, '')
        self.drv.zfssa.set_lun_initiatorgroup.assert_called_once_with(
            lcfg.zfssa_pool,
            lcfg.zfssa_project,
            self.test_vol['name'],
            '')

    def test_get_volume_stats(self):
        self.drv.zfssa.get_pool_stats.return_value = 2 * units.Gi, 3 * units.Gi
        lcfg = self.configuration
        stats = self.drv.get_volume_stats(refresh=True)
        self.drv.zfssa.get_pool_stats.assert_called_once_with(lcfg.zfssa_pool)
        self.assertEqual('Oracle', stats['vendor_name'])
        self.assertEqual(self.configuration.volume_backend_name,
                         stats['volume_backend_name'])
        self.assertEqual(self.drv.VERSION, stats['driver_version'])
        self.assertEqual(self.drv.protocol, stats['storage_protocol'])
        self.assertEqual(0, stats['reserved_percentage'])
        self.assertFalse(stats['QoS_support'])
        self.assertEqual(3, stats['total_capacity_gb'])
        self.assertEqual(2, stats['free_capacity_gb'])

    def test_extend_volume(self):
        lcfg = self.configuration
        self.drv.extend_volume(self.test_vol, 3)
        self.drv.zfssa.set_lun_props.assert_called_once_with(
            lcfg.zfssa_pool,
            lcfg.zfssa_project,
            self.test_vol['name'],
            volsize= 3 * units.Gi)

    @mock.patch('cinder.volume.volume_types.get_volume_type_extra_specs')
    def test_get_voltype_specs(self, get_volume_type_extra_specs):
        volume_type_id = mock.sentinel.volume_type_id
        volume = {'volume_type_id': volume_type_id}
        get_volume_type_extra_specs.return_value = {
            'zfssa:volblocksize': '128k',
            'zfssa:compression': 'gzip'
        }
        ret = self.drv._get_voltype_specs(volume)
        self.assertEqual('128k', ret.get('volblocksize'))
        self.assertEqual(self.configuration.zfssa_lun_sparse,
                         ret.get('sparse'))
        self.assertEqual('gzip', ret.get('compression'))
        self.assertEqual(self.configuration.zfssa_lun_logbias,
                         ret.get('logbias'))

    def tearDown(self):
        super(TestZFSSAISCSIDriver, self).tearDown()

    def fake_safe_get(self, value):
        try:
            val = getattr(self.configuration, value)
        except AttributeError:
            val = None
        return val


class TestZFSSANFSDriver(test.TestCase):

    test_vol = {
        'name': 'test-vol',
        'size': 1,
        'id': '1'
    }

    test_snap = {
        'name': 'cindersnap',
        'volume_name': test_vol['name'],
        'volume_size': test_vol['size']
    }

    test_vol_snap = {
        'name': 'cindersnapvol',
        'size': test_vol['size']
    }

    def __init__(self, method):
        super(TestZFSSANFSDriver, self).__init__(method)

    @mock.patch.object(zfssanfs, 'factory_zfssa')
    def setUp(self, _factory_zfssa):
        super(TestZFSSANFSDriver, self).setUp()
        self._create_fake_config()
        _factory_zfssa.return_value = mock.MagicMock(spec=rest.ZFSSANfsApi)
        self.drv = zfssanfs.ZFSSANFSDriver(configuration=self.configuration)
        self.drv._execute = fake_utils.fake_execute
        self.drv.do_setup({})

    def _create_fake_config(self):
        self.configuration = mock.Mock(spec=conf.Configuration)
        self.configuration.san_ip = '1.1.1.1'
        self.configuration.san_login = 'user'
        self.configuration.san_password = 'passwd'
        self.configuration.zfssa_data_ip = '2.2.2.2'
        self.configuration.zfssa_https_port = '443'
        self.configuration.zfssa_nfs_pool = 'pool'
        self.configuration.zfssa_nfs_project = 'nfs_project'
        self.configuration.zfssa_nfs_share = 'nfs_share'
        self.configuration.zfssa_nfs_share_logbias = nfs_logbias
        self.configuration.zfssa_nfs_share_compression = nfs_compression
        self.configuration.zfssa_nfs_mount_options = ''
        self.configuration.zfssa_rest_timeout = '30'
        self.configuration.nfs_oversub_ratio = 1
        self.configuration.nfs_used_ratio = 1

    def test_migrate_volume(self):
        self.drv.zfssa.get_asn.return_value = (
            '9a2b5a0f-e3af-6d14-9578-8825f229dc89')
        volume = self.test_vol
        volume.update({'host': 'fake_host',
                       'status': 'available',
                       'name': 'vol-1',
                       'source_volid': self.test_vol['id']})

        loc_info = '9a2b5a0f-e3af-6d14-9578-8825f229dc89:nfs_share'

        host = {'host': 'stack@zfssa_nfs#fake_zfssa',
                'capabilities': {'vendor_name': 'Oracle',
                                 'storage_protocol': 'nfs',
                                 'location_info': loc_info}}
        ctxt = context.get_admin_context()

        # Test Normal case
        result = self.drv.migrate_volume(ctxt, volume, host)
        self.assertEqual((True, None), result)

        # Test when volume status is not available
        volume['status'] = 'in-use'
        result = self.drv.migrate_volume(ctxt, volume, host)
        self.assertEqual((False, None), result)
        volume['status'] = 'available'

        # Test when Vendor is not Oracle
        host['capabilities']['vendor_name'] = 'elcarO'
        result = self.drv.migrate_volume(ctxt, volume, host)
        self.assertEqual((False, None), result)
        host['capabilities']['vendor_name'] = 'Oracle'

        # Test when storage protocol is not iSCSI
        host['capabilities']['storage_protocol'] = 'not_nfs'
        result = self.drv.migrate_volume(ctxt, volume, host)
        self.assertEqual((False, None), result)
        host['capabilities']['storage_protocol'] = 'nfs'

        # Test for exceptions
        host['capabilities']['location_info'] = ''
        result = self.drv.migrate_volume(ctxt, volume, host)
        self.assertEqual((False, None), result)
        host['capabilities']['location_info'] = loc_info

        # Test case when source and target asn dont match
        invalid_loc_info = (
            'fake_asn*https://2.2.2.2:/shares/export/nfs_share*nfs_share')
        host['capabilities']['location_info'] = invalid_loc_info
        result = self.drv.migrate_volume(ctxt, volume, host)
        self.assertEqual((False, None), result)

        # Test case when source and target shares names are different
        invalid_loc_info = (
            '9a2b5a0f-e3af-6d14-9578-8825f229dc89*' +
            'https://tgt:/shares/export/nfs_share*nfs_share_1')
        host['capabilities']['location_info'] = invalid_loc_info
        result = self.drv.migrate_volume(ctxt, volume, host)
        self.assertEqual((False, None), result)

    def test_create_delete_snapshot(self):
        lcfg = self.configuration
        self.drv.create_snapshot(self.test_snap)
        self.drv.zfssa.create_snapshot.assert_called_once_with(
            lcfg.zfssa_nfs_pool,
            lcfg.zfssa_nfs_project,
            lcfg.zfssa_nfs_share,
            mock.ANY)
        self.drv.zfssa.create_snapshot_of_volume_file.assert_called_once_with(
            src_file=mock.ANY,
            dst_file=self.test_snap['name'])
        self.drv.delete_snapshot(self.test_snap)
        self.drv.zfssa.delete_snapshot_of_volume_file.assert_called_with(
            src_file=self.test_snap['name'])

    def test_create_volume_from_snapshot(self):
        self.drv.create_snapshot(self.test_snap)
        with mock.patch.object(self.drv, '_ensure_shares_mounted'):
            self.drv.create_volume_from_snapshot(self.test_vol_snap,
                                                 self.test_snap,
                                                 method='COPY')

        self.drv.zfssa.create_volume_from_snapshot_file.\
            assert_called_once_with(src_file=self.test_snap['name'],
                                    dst_file=self.test_vol_snap['name'],
                                    method='COPY')

    def test_get_volume_stats(self):
        self.drv._mounted_shares = ['nfs_share']
        with mock.patch.object(self.drv, '_ensure_shares_mounted'):
            with mock.patch.object(self.drv, '_get_share_capacity_info') as \
                    mock_get_share_capacity_info:
                mock_get_share_capacity_info.return_value = (1073741824,
                                                             9663676416)
                stats = self.drv.get_volume_stats(refresh=True)
                self.assertEqual(1, stats['free_capacity_gb'])
                self.assertEqual(10, stats['total_capacity_gb'])

    def tearDown(self):
        super(TestZFSSANFSDriver, self).tearDown()


class TestZFSSAApi(test.TestCase):

    @mock.patch.object(rest, 'factory_restclient')
    def setUp(self, _restclient):
        super(TestZFSSAApi, self).setUp()
        self.host = 'fakehost'
        self.user = 'fakeuser'
        self.url = None
        self.pool = 'fakepool'
        self.project = 'fakeproject'
        self.vol = 'fakevol'
        self.snap = 'fakesnapshot'
        self.clone = 'fakeclone'
        self.targetalias = 'fakealias'
        _restclient.return_value = mock.MagicMock(spec=client.RestClientURL)
        self.zfssa = rest.ZFSSAApi()
        self.zfssa.set_host('fakehost')
        self.pool_url = '/api/storage/v1/pools/'

    def _create_response(self, status, data='data'):
        response = FakeResponse(status, data)
        return response

    def test_create_project(self):
        self.zfssa.rclient.get.return_value = self._create_response(
            client.Status.OK)
        self.zfssa.create_project(self.pool, self.project)
        expected_svc = self.pool_url + self.pool + '/projects/' + self.project
        self.zfssa.rclient.get.assert_called_with(expected_svc)

    def test_create_initiator(self):
        self.zfssa.rclient.get.return_value = self._create_response(
            client.Status.OK)
        initiator = 'iqn.1986-03.com.sun:02:00000-aaaa-bbbb-cccc-ddddd'
        alias = 'init-group'
        self.zfssa.create_initiator(initiator, alias)
        self.zfssa.rclient.get.assert_called_with(
            '/api/san/v1/iscsi/initiators/alias=' + alias)

    def test_create_target(self):
        self.zfssa.rclient.get.return_value = self._create_response(
            client.Status.NOT_FOUND)
        ret_val = json.dumps(
            {'target': {'iqn':
                        'iqn.1986-03.com.sun:02:00000-aaaa-bbbb-cccc-ddddd'}})
        self.zfssa.rclient.post.return_value = self._create_response(
            client.Status.CREATED, ret_val)
        alias = 'tgt-group'
        self.zfssa.create_target(alias)
        self.zfssa.rclient.post.assert_called_with('/api/san/v1/iscsi/targets',
                                                   {'alias': alias})

    def test_get_target(self):
        ret_val = json.dumps(
            {'target': {'href': 'fake_href',
                        'alias': 'tgt-group',
                        'iqn':
                        'iqn.1986-03.com.sun:02:00000-aaaa-bbbb-cccc-ddddd',
                        'targetchapuser': '',
                        'targetchapsecret': '',
                        'interfaces': ['nge0']}})
        self.zfssa.rclient.get.return_value = self._create_response(
            client.Status.OK, ret_val)
        ret = self.zfssa.get_target('tgt-group')
        self.zfssa.rclient.get.assert_called_once_with(
            '/api/san/v1/iscsi/targets/alias=tgt-group')
        self.assertEqual('iqn.1986-03.com.sun:02:00000-aaaa-bbbb-cccc-ddddd',
                         ret)

    def test_verify_pool(self):
        self.zfssa.rclient.get.return_value = self._create_response(
            client.Status.OK)
        self.zfssa.verify_pool(self.pool)
        self.zfssa.rclient.get.assert_called_with(self.pool_url + self.pool)

    def test_verify_project(self):
        self.zfssa.rclient.get.return_value = self._create_response(
            client.Status.NOT_FOUND)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.zfssa.verify_project,
                          self.pool,
                          self.project)

    def test_verify_initiator(self):
        self.zfssa.rclient.get.return_value = self._create_response(
            client.Status.OK)
        self.zfssa.verify_initiator('iqn.1-0.org.deb:01:d7')
        self.zfssa.rclient.get.assert_called_with(
            '/api/san/v1/iscsi/initiators/iqn.1-0.org.deb:01:d7')

    def test_verify_target(self):
        self.zfssa.rclient.get.return_value = self._create_response(
            client.Status.BAD_REQUEST)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.zfssa.verify_target,
                          self.targetalias)

    def test_create_delete_lun(self):
        arg = json.dumps({'name': self.vol,
                          'initiatorgroup': 'com.sun.ms.vss.hg.maskAll'})
        self.zfssa.rclient.post.return_value = self._create_response(
            client.Status.CREATED, data=arg)
        self.zfssa.create_lun(self.pool, self.project, self.vol, 1, 'tgt-grp',
                              None)
        expected_arg = {'name': self.vol,
                        'volsize': 1,
                        'targetgroup': 'tgt-grp',
                        'initiatorgroup': 'com.sun.ms.vss.hg.maskAll'}
        self.zfssa.rclient.post.assert_called_with(
            self.pool_url + self.pool + '/projects/' + self.project + '/luns',
            expected_arg)

        self.zfssa.rclient.delete.return_value = self._create_response(
            client.Status.NO_CONTENT)
        self.zfssa.delete_lun(self.pool, self.project, self.vol)
        self.zfssa.rclient.delete.assert_called_with(
            self.pool_url + self.pool + '/projects/' + self.project +
            '/luns/' + self.vol)

    def test_create_delete_snapshot(self):
        self.zfssa.rclient.post.return_value = self._create_response(
            client.Status.CREATED)
        self.zfssa.create_snapshot(self.pool,
                                   self.project,
                                   self.vol,
                                   self.snap)
        expected_arg = {'name': self.snap}
        self.zfssa.rclient.post.assert_called_with(
            self.pool_url + self.pool + '/projects/' + self.project +
            '/luns/' + self.vol + '/snapshots', expected_arg)

        self.zfssa.rclient.delete.return_value = self._create_response(
            client.Status.NO_CONTENT)
        self.zfssa.delete_snapshot(self.pool,
                                   self.project,
                                   self.vol,
                                   self.snap)
        self.zfssa.rclient.delete.assert_called_with(
            self.pool_url + self.pool + '/projects/' + self.project +
            '/luns/' + self.vol + '/snapshots/' + self.snap)

    def test_clone_snapshot(self):
        self.zfssa.rclient.put.return_value = self._create_response(
            client.Status.CREATED)
        self.zfssa.clone_snapshot(self.pool,
                                  self.project,
                                  self.vol,
                                  self.snap,
                                  self.clone)
        expected_svc = '/api/storage/v1/pools/' + self.pool + '/projects/' + \
            self.project + '/luns/' + self.vol + '/snapshots/' + self.snap + \
            '/clone'
        expected_arg = {'project': self.project,
                        'share': self.clone,
                        'nodestroy': True}
        self.zfssa.rclient.put.assert_called_with(expected_svc, expected_arg)


class TestZFSSANfsApi(test.TestCase):

    @mock.patch.object(rest, 'factory_restclient')
    def setUp(self, _restclient):
        super(TestZFSSANfsApi, self).setUp()
        self.host = 'fakehost'
        self.user = 'fakeuser'
        self.url = None
        self.pool = 'fakepool'
        self.project = 'fakeproject'
        self.share = 'fakeshare'
        self.snap = 'fakesnapshot'
        self.targetalias = 'fakealias'
        _restclient.return_value = mock.MagicMock(spec=client.RestClientURL)
        self.webdavclient = mock.MagicMock(spec=webdavclient.ZFSSAWebDAVClient)
        self.zfssa = rest.ZFSSANfsApi()
        self.zfssa.set_host('fakehost')
        self.pool_url = '/api/storage/v1/pools/'

    def _create_response(self, status, data='data'):
        response = FakeResponse(status, data)
        return response

    def test_verify_share(self):
        self.zfssa.rclient.get.return_value = self._create_response(
            client.Status.OK)
        self.zfssa.verify_share(self.pool, self.project, self.share)
        self.zfssa.rclient.get.assert_called_with(self.pool_url + self.pool +
                                                  '/projects/' + self.project +
                                                  '/filesystems/' + self.share)

    def test_create_delete_snapshot(self):
        self.zfssa.rclient.post.return_value = self._create_response(
            client.Status.CREATED)
        self.zfssa.create_snapshot(self.pool,
                                   self.project,
                                   self.share,
                                   self.snap)
        expected_arg = {'name': self.snap}
        self.zfssa.rclient.post.assert_called_with(
            self.pool_url + self.pool + '/projects/' + self.project +
            '/filesystems/' + self.share + '/snapshots', expected_arg)

        self.zfssa.rclient.delete.return_value = self._create_response(
            client.Status.NO_CONTENT)
        self.zfssa.delete_snapshot(self.pool,
                                   self.project,
                                   self.share,
                                   self.snap)
        self.zfssa.rclient.delete.assert_called_with(
            self.pool_url + self.pool + '/projects/' + self.project +
            '/filesystems/' + self.share + '/snapshots/' + self.snap)

    def create_delete_snapshot_of_volume_file(self):
        src_file = "fake_src_file"
        dst_file = "fake_dst_file"
        self.zfssa.create_snapshot_of_volume_file(src_file=src_file,
                                                  dst_file=dst_file)
        self.zfssa.webdavclient.request.assert_called_once_with(
            src_file=src_file,
            dst_file=dst_file,
            method='COPY')
        self.zfssa.delete_snapshot_of_volume_file(src_file=src_file)
        self.zfssa.webdavclient.request.assert_called_once_with(
            src_file=src_file, method='DELETE')

    def test_get_share(self):
        ret_val = json.dumps({'filesystem': 'test_fs'})
        self.zfssa.rclient.get.return_value = self._create_response(
            client.Status.OK, ret_val)
        ret = self.zfssa.get_share(self.pool, self.project, self.share)
        self.zfssa.rclient.get.assert_called_with(self.pool_url + self.pool +
                                                  '/projects/' + self.project +
                                                  '/filesystems/' + self.share)
        self.assertEqual('test_fs', ret)

    def test_create_share(self):
        self.zfssa.rclient.get.return_value = self._create_response(
            client.Status.NOT_FOUND)
        self.zfssa.rclient.post.return_value = self._create_response(
            client.Status.BAD_REQUEST)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.zfssa.create_share,
                          self.pool,
                          self.project,
                          self.share,
                          {})

    @mock.patch.object(rest.ZFSSANfsApi, '_change_service_state')
    @mock.patch.object(rest.ZFSSANfsApi, 'verify_service')
    def test_enable_disable_modify_service(self,
                                           verify_service,
                                           _change_service_state):
        self.zfssa.enable_service('http')
        self.zfssa._change_service_state.assert_called_with(
            'http', state='enable')
        self.zfssa.verify_service.assert_called_with('http')

        self.zfssa.disable_service('http')
        self.zfssa._change_service_state.assert_called_with(
            'http', state='disable')
        self.zfssa.verify_service.assert_called_with('http', status='offline')

        ret_val = json.dumps({'service': {
            "href": "/api/service/v1/services/http",
            "<status>": "online",
            "require_login": False,
            "protocols": "http/https",
            "listen_port": 81,
            "https_port": 443}})
        self.zfssa.rclient.put.return_value = self._create_response(
            client.Status.ACCEPTED, ret_val)
        args = {'listen_port': 81}
        self.zfssa.modify_service('http', args)
        self.zfssa.rclient.put.called_with('/api/service/v1/services/http',
                                           args)


class TestRestClientURL(test.TestCase):
    def setUp(self):
        super(TestRestClientURL, self).setUp()
        self.timeout = 60
        self.url = '1.1.1.1'
        self.client = client.RestClientURL(self.url, timeout=self.timeout)

    @mock.patch.object(client.RestClientURL, 'request')
    def test_post(self, _request):
        path = '/api/storage/v1/pools'
        body = {'name': 'fakepool'}
        self.client.post(path, body=body)
        self.client.request.assert_called_with(path, 'POST', body)

    @mock.patch.object(client.RestClientURL, 'request')
    def test_get(self, _request):
        path = '/api/storage/v1/pools'
        self.client.get(path)
        self.client.request.assert_called_with(path, 'GET')

    @mock.patch.object(client.RestClientURL, 'request')
    def test_put(self, _request):
        path = '/api/storage/v1/pools'
        body = {'name': 'fakepool'}
        self.client.put(path, body=body)
        self.client.request.assert_called_with(path, 'PUT', body)

    @mock.patch.object(client.RestClientURL, 'request')
    def test_delete(self, _request):
        path = '/api/storage/v1/pools'
        self.client.delete(path)
        self.client.request.assert_called_with(path, 'DELETE')

    @mock.patch.object(client.RestClientURL, 'request')
    def test_head(self, _request):
        path = '/api/storage/v1/pools'
        self.client.head(path)
        self.client.request.assert_called_with(path, 'HEAD')

    @mock.patch.object(client, 'RestResult')
    @mock.patch.object(client.urllib.request, 'Request')
    @mock.patch.object(client.urllib.request, 'urlopen')
    def test_request(self, _urlopen, _Request, _RestResult):
        path = '/api/storage/v1/pools'
        _urlopen.return_value = mock.Mock()
        self.client.request(path, mock.ANY)
        _Request.assert_called_with(self.url + path, None, self.client.headers)
        self.assertEqual(1, _urlopen.call_count)
        _RestResult.assert_called_with(response=mock.ANY)

    @mock.patch.object(client, 'RestResult')
    @mock.patch.object(client.urllib.request, 'Request')
    @mock.patch.object(client.urllib.request, 'urlopen')
    @mock.patch.object(client, 'ssl', new_callable=FakeSSL)
    def test_ssl_with_context(self, _ssl, _urlopen, _Request, _RestResult):
        """Test PEP476 certificate opt_out fix. """
        path = '/api/storage/v1/pools'
        _urlopen.return_value = mock.Mock()
        self.client.request(path, mock.ANY)
        _urlopen.assert_called_once_with(mock.ANY,
                                         timeout=self.timeout,
                                         context='fakecontext')

    @mock.patch.object(client, 'RestResult')
    @mock.patch.object(client.urllib.request, 'Request')
    @mock.patch.object(client.urllib.request, 'urlopen')
    @mock.patch.object(client, 'ssl', new_callable=object)
    def test_ssl_no_context(self, _ssl, _urlopen, _Request, _RestResult):
        """Verify the PEP476 fix backward compatibility. """
        path = '/api/storage/v1/pools'
        _urlopen.return_value = mock.Mock()
        self.client.request(path, mock.ANY)
        _urlopen.assert_called_once_with(mock.ANY, timeout=self.timeout)
