# Blackbox tests for "samba-tool drs" command
# Copyright (C) Kamen Mazdrashki <kamenim@samba.org> 2011
# Copyright (C) Andrew Bartlett <abartlet@samba.org> 2017
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

"""Blackbox tests for samba-tool drs showrepl."""
from __future__ import print_function
import samba.tests
import drs_base
from samba.dcerpc import drsuapi
from samba import drs_utils
import re
import json
import ldb
import random
from samba.compat import PY3

if PY3:
    json_str = str
else:
    json_str = unicode

GUID_RE = r'[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}'
HEX8_RE = r'0x[\da-f]{8}'
DN_RE = r'(?:(?:CN|DC)=[\\:\w -]+,)+DC=com'


class SambaToolDrsShowReplTests(drs_base.DrsBaseTestCase):
    """Blackbox test case for samba-tool drs."""

    def assertRegex(self, exp, s, flags=0):
        m = re.search(exp, s, flags=flags)
        if m is None:
            self.fail("%r did not match /%s/" % (s, exp))
        return m

    def setUp(self):
        super(SambaToolDrsShowReplTests, self).setUp()

        self.dc1 = samba.tests.env_get_var_value("DC1")
        self.dc2 = samba.tests.env_get_var_value("DC2")

        creds = self.get_credentials()
        self.cmdline_creds = "-U%s/%s%%%s" % (creds.get_domain(),
                                              creds.get_username(),
                                              creds.get_password())

    def test_samba_tool_showrepl(self):
        """Tests 'samba-tool drs showrepl' command.
        """
        # Output should be like:
        #      <site-name>/<domain-name>
        #      DSA Options: <hex-options>
        #      DSA object GUID: <DSA-object-GUID>
        #      DSA invocationId: <DSA-invocationId>
        #      <Inbound-connections-list>
        #      <Outbound-connections-list>
        #      <KCC-objects>
        #      ...
        #   TODO: Perhaps we should check at least for
        #         DSA's objectGUDI and invocationId
        out = self.check_output("samba-tool drs showrepl "
                                "%s %s" % (self.dc1, self.cmdline_creds))

        # We want to assert that we are getting the same results, but
        # dates and GUIDs change randomly.
        #
        # There are sections with headers like ==== THIS ===="
        (header,
         _inbound, inbound,
         _outbound, outbound,
         _conn, conn) = out.split("====")

        self.assertEqual(_inbound, ' INBOUND NEIGHBORS ')
        self.assertEqual(_outbound, ' OUTBOUND NEIGHBORS ')
        self.assertEqual(_conn, ' KCC CONNECTION OBJECTS ')

        self.assertRegex(r'^Default-First-Site-Name\\LOCALDC\s+'
                         r"DSA Options: %s\s+"
                         r"DSA object GUID: %s\s+"
                         r"DSA invocationId: %s" %
                         (HEX8_RE, GUID_RE, GUID_RE), header)

        # We don't assert the DomainDnsZones and ForestDnsZones are
        # there because we don't know that they have been set up yet.

        for p in ['CN=Configuration,DC=samba,DC=example,DC=com',
                  'DC=samba,DC=example,DC=com',
                  'CN=Schema,CN=Configuration,DC=samba,DC=example,DC=com']:
            self.assertRegex(r'%s\n'
                             r'\tDefault-First-Site-Name\\[A-Z]+ via RPC\n'
                             r'\t\tDSA object GUID: %s\n'
                             r'\t\tLast attempt @ [^\n]+\n'
                             r'\t\t\d+ consecutive failure\(s\).\n'
                             r'\t\tLast success @ [^\n]+\n'
                             r'\n' % (p, GUID_RE), inbound)

            self.assertRegex(r'%s\n'
                             r'\tDefault-First-Site-Name\\[A-Z]+ via RPC\n'
                             r'\t\tDSA object GUID: %s\n'
                             r'\t\tLast attempt @ [^\n]+\n'
                             r'\t\t\d+ consecutive failure\(s\).\n'
                             r'\t\tLast success @ [^\n]+\n'
                             r'\n' % (p, GUID_RE), outbound)

        self.assertRegex(r'Connection --\n'
                         r'\tConnection name: %s\n'
                         r'\tEnabled        : TRUE\n'
                         r'\tServer DNS name : \w+.samba.example.com\n'
                         r'\tServer DN name  : %s'
                         r'\n' % (GUID_RE, DN_RE), conn)

    def test_samba_tool_showrepl_json(self):
        """Tests 'samba-tool drs showrepl --json' command.
        """
        out = self.check_output("samba-tool drs showrepl %s %s --json" %
                                (self.dc1, self.cmdline_creds))

        print(out)

        d = json.loads(out)
        self.assertEqual(set(d), set(['repsFrom',
                                      'repsTo',
                                      "NTDSConnections",
                                      "dsa"]))

        # dsa
        for k in ["objectGUID", "invocationId"]:
            self.assertRegex('^%s$' % GUID_RE, d['dsa'][k])
        self.assertTrue(isinstance(d['dsa']["options"], int))

        # repsfrom and repsto
        for reps in (d['repsFrom'], d['repsTo']):
            for r in reps:
                for k in ('NC dn', "NTDS DN"):
                    self.assertRegex('^%s$' % DN_RE, r[k])
                for k in ("last attempt time",
                          "last attempt message",
                          "last success"):
                    self.assertTrue(isinstance(r[k], json_str))
                self.assertRegex('^%s$' % GUID_RE, r["DSA objectGUID"])
                self.assertTrue(isinstance(r["consecutive failures"], int))

        # ntdsconnection
        for n in d["NTDSConnections"]:
            self.assertRegex(r'^[\w]+\.samba\.example\.com$', n["dns name"])
            self.assertRegex("^%s$" % GUID_RE, n["name"])
            self.assertTrue(isinstance(n['enabled'], bool))
            self.assertTrue(isinstance(n['options'], int))
            self.assertTrue(isinstance(n['replicates NC'], list))
            self.assertRegex("^%s$" % DN_RE, n["remote DN"])

    def _force_all_reps(self, samdb, dc, direction):
        if direction == 'inbound':
            info_type = drsuapi.DRSUAPI_DS_REPLICA_INFO_NEIGHBORS
        elif direction == 'outbound':
            info_type = drsuapi.DRSUAPI_DS_REPLICA_INFO_REPSTO
        else:
            raise ValueError("expected 'inbound' or 'outbound'")

        self._enable_all_repl(dc)
        lp = self.get_loadparm()
        creds = self.get_credentials()
        drsuapi_conn, drsuapi_handle, _ = drs_utils.drsuapi_connect(dc, lp, creds)
        req1 = drsuapi.DsReplicaGetInfoRequest1()
        req1.info_type = info_type
        _, info = drsuapi_conn.DsReplicaGetInfo(drsuapi_handle, 1, req1)
        for x in info.array:
            # you might think x.source_dsa_address was the thing, but no.
            # and we need to filter out RODCs and deleted DCs

            res = []
            try:
                res = samdb.search(base=x.source_dsa_obj_dn,
                                   scope=ldb.SCOPE_BASE,
                                   attrs=['msDS-isRODC', 'isDeleted'],
                                   controls=['show_deleted:0'])
            except ldb.LdbError as e:
                if e.args[0] != ldb.ERR_NO_SUCH_OBJECT:
                    raise

            if (len(res) == 0 or
                len(res[0].get('msDS-isRODC', '')) > 0 or
                res[0]['isDeleted'] == 'TRUE'):
                continue

            dsa_dn = str(ldb.Dn(samdb, x.source_dsa_obj_dn).parent())
            res = samdb.search(base=dsa_dn,
                               scope=ldb.SCOPE_BASE,
                               attrs=['dNSHostName'])

            remote = res[0]['dNSHostName'][0]
            self._enable_all_repl(remote)
            if direction == 'inbound':
                src, dest = remote, dc
            else:
                src, dest = dc, remote
            self._net_drs_replicate(dest, src, forced=True)

    def test_samba_tool_showrepl_summary_all_good(self):
        """Tests 'samba-tool drs showrepl --summary' command."""
        # To be sure that all is good we need to force replication
        # with everyone (because others might have it turned off), and
        # turn replication on for them in case they suddenly decide to
        # try again.
        #
        # We don't restore them to the non-auto-replication state.
        samdb1 = self.getSamDB("-H", "ldap://%s" % self.dc1, "-U",
                               self.cmdline_creds)
        self._enable_all_repl(self.dc1)
        self._force_all_reps(samdb1, self.dc1, 'inbound')
        self._force_all_reps(samdb1, self.dc1, 'outbound')

        out = self.check_output("samba-tool drs showrepl --summary %s %s" %
                                (self.dc1, self.cmdline_creds))
        self.assertStringsEqual(out, "[ALL GOOD]\n")

        out = self.check_output("samba-tool drs showrepl --summary "
                                "--color=yes %s %s" %
                                (self.dc1, self.cmdline_creds))
        self.assertStringsEqual(out, "\033[1;32m[ALL GOOD]\033[0m\n")

        # --verbose output is still quiet when all is good.
        out = self.check_output("samba-tool drs showrepl --summary -v %s %s" %
                                (self.dc1, self.cmdline_creds))
        self.assertStringsEqual(out, "[ALL GOOD]\n")
        out = self.check_output("samba-tool drs showrepl --summary -v "
                                "--color=yes %s %s" %
                                (self.dc1, self.cmdline_creds))
        self.assertStringsEqual(out, "\033[1;32m[ALL GOOD]\033[0m\n")

    def test_samba_tool_showrepl_summary_forced_failure(self):
        """Tests 'samba-tool drs showrepl --summary' command when we break the
        network on purpose.
        """
        self.addCleanup(self._enable_all_repl, self.dc1)
        self._disable_all_repl(self.dc1)

        samdb1 = self.getSamDB("-H", "ldap://%s" % self.dc1, "-U",
                               self.cmdline_creds)
        samdb2 = self.getSamDB("-H", "ldap://%s" % self.dc2, "-U",
                               self.cmdline_creds)
        domain_dn = samdb1.domain_dn()

        # Add some things to NOT replicate
        ou1 = "OU=dc1.%x,%s" % (random.randrange(1 << 64), domain_dn)
        ou2 = "OU=dc2.%x,%s" % (random.randrange(1 << 64), domain_dn)
        samdb1.add({
            "dn": ou1,
            "objectclass": "organizationalUnit"
        })
        self.addCleanup(samdb1.delete, ou1, ['tree_delete:1'])
        samdb2.add({
            "dn": ou2,
            "objectclass": "organizationalUnit"
        })
        self.addCleanup(samdb2.delete, ou2, ['tree_delete:1'])

        dn1 = 'cn=u1.%%d,%s' % (ou1)
        dn2 = 'cn=u2.%%d,%s' % (ou2)

        try:
            for i in range(100):
                samdb1.add({
                    "dn": dn1 % i,
                    "objectclass": "user"
                })
                samdb2.add({
                    "dn": dn2 % i,
                    "objectclass": "user"
                })
                out = self.check_output("samba-tool drs showrepl --summary -v "
                                        "%s %s" %
                                        (self.dc1, self.cmdline_creds))
                self.assertStringsEqual('[ALL GOOD]', out, strip=True)
                out = self.check_output("samba-tool drs showrepl --summary -v "
                                        "--color=yes %s %s" %
                                        (self.dc2, self.cmdline_creds))
                self.assertIn('[ALL GOOD]', out)

        except samba.tests.BlackboxProcessError as e:
            print("Good, failed as expected after %d rounds: %r" % (i, e.cmd))
            self.assertIn('There are failing connections', e.stdout)
            self.assertRegexpMatches(e.stdout,
                                     r'result 845[67] '
                                     r'\(WERR_DS_DRA_(SINK|SOURCE)_DISABLED\)',
                                     msg=("The process should have failed "
                                          "because replication was forced off, "
                                          "but it failed for some other reason."))
            self.assertIn('consecutive failure(s).', e.stdout)
        else:
            self.fail("No DRS failure noticed after 100 rounds of trying")