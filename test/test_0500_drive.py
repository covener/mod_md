# test driving the ACME protocol

import base64
import json
import os.path
import pytest
import re
import sys
import time
import urllib

from datetime import datetime
from test_base import TestEnv
from test_base import HttpdConf
from test_base import CertUtil

def setup_module(module):
    print("setup_module: %s" % module.__name__)
    TestEnv.init()
    TestEnv.check_acme()
    TestEnv.apache_err_reset()
    TestEnv.APACHE_CONF_SRC = "data/test_drive"
    assert TestEnv.apache_restart() == 0

def teardown_module(module):
    print("teardown_module:%s" % module.__name__)
    assert TestEnv.apache_stop() == 0

class TestDrive :

    @classmethod
    def setup_class(cls):
        time.sleep(1)
        cls.dns_uniq = "%d.org" % time.time()
        cls.TMP_CONF = os.path.join(TestEnv.GEN_DIR, "auto.conf")

    def setup_method(self, method):
        print("setup_method: %s" % method.__name__)
        TestEnv.clear_store()
        TestEnv.install_test_conf()

    def teardown_method(self, method):
        print("teardown_method: %s" % method.__name__)

    # --------- invalid precondition ---------

    def test_500_000(self):
        # test case: md without contact info
        domain = "test500-000-" + TestDrive.dns_uniq
        name = "www." + domain
        assert TestEnv.a2md( [ "add", name ] )['rv'] == 0
        run = TestEnv.a2md( [ "drive", name ] )
        assert run['rv'] == 1
        assert re.search("no contact information", run["stderr"])

    def test_500_001(self):
        # test case: md with contact, but without TOS
        domain = "test500-001-" + TestDrive.dns_uniq
        name = "www." + domain
        assert TestEnv.a2md( [ "add", name ] )['rv'] == 0
        assert TestEnv.a2md( 
            [ "update", name, "contacts", "admin@test1.example.org" ] 
            )['rv'] == 0
        run = TestEnv.a2md( [ "drive", name ] )
        assert run['rv'] == 1
        assert re.search("the CA requires you to accept the terms-of-service as specified in ", run["stderr"])

    
    # test_102 removed, was based on false assumption
    
    def test_500_003(self):
        # test case: md with unknown protocol FOO
        domain = "test500-003-" + TestDrive.dns_uniq
        name = "www." + domain
        self._prepare_md([ name ])
        assert TestEnv.a2md(
            [ "update", name, "ca", TestEnv.ACME_URL, "FOO"]
            )['rv'] == 0
        run = TestEnv.a2md( [ "drive", name ] )
        assert run['rv'] == 1
        assert re.search("unknown CA protocol", run["stderr"])

    # --------- driving OK ---------

    def test_500_100(self):
        # test case: md with one domain
        domain = "test500-100-" + TestDrive.dns_uniq
        name = "www." + domain
        self._prepare_md([ name ])
        assert TestEnv.apache_start() == 0
        # drive
        prevMd = TestEnv.a2md([ "list", name ])['jout']['output'][0]
        assert TestEnv.a2md( [ "drive", "-c", "http-01", name ] )['rv'] == 0
        self._check_md_cert([ name ])
        self._check_account_key( name )

        # check: challenges removed
        TestEnv.check_dir_empty( TestEnv.path_challenges() )
        # check archive content
        assert json.loads( open( TestEnv.path_domain(name, archiveVersion=1 )).read() ) == prevMd

        # check file system permissions:
        TestEnv.check_file_permissions( name )

    def test_500_101(self):
        # test case: md with 2 domains
        domain = "test500-101-" + TestDrive.dns_uniq
        name = "www." + domain
        self._prepare_md([ name, "test." + domain ])
        assert TestEnv.apache_start() == 0
        # drive
        assert TestEnv.a2md( [ "-vv", "drive", "-c", "http-01", name ] )['rv'] == 0
        self._check_md_cert([ name, "test." + domain ])

    def test_500_102(self):
        # test case: md with one domain, local TOS agreement and ACME account
        # setup: create md
        domain = "test500-102-" + TestDrive.dns_uniq
        name = "www." + domain
        self._prepare_md([ name ])
        assert TestEnv.apache_start() == 0
        # setup: create account on server
        run = TestEnv.a2md( ["acme", "newreg", "admin@" + domain], raw=True )
        assert run['rv'] == 0
        acct = re.match("registered: (.*)$", run["stdout"]).group(1)
        # setup: link md to account
        assert TestEnv.a2md([ "update", name, "account", acct])['rv'] == 0
        # drive
        assert TestEnv.a2md( [ "-vv", "drive", "-c", "tls-sni-01", name ] )['rv'] == 0
        self._check_md_cert([ name ])

    def test_500_103(self):
        # test case: md with one domain, ACME account and TOS agreement on server
        # setup: create md
        domain = "test500-103-" + TestDrive.dns_uniq
        name = "www." + domain
        assert TestEnv.a2md(["add", name])['rv'] == 0
        assert TestEnv.a2md([ "update", name, "contacts", "admin@" + domain ])['rv'] == 0
        assert TestEnv.apache_start() == 0
        # setup: create account on server
        run = TestEnv.a2md( ["acme", "newreg", "admin@" + domain], raw=True )
        assert run['rv'] == 0
        acct = re.match("registered: (.*)$", run["stdout"]).group(1)
        # setup: send TOS agreement to server
        assert TestEnv.a2md(["--terms", TestEnv.ACME_TOS, "acme", "agree", acct])['rv'] == 0
        # setup: link md to account
        assert TestEnv.a2md([ "update", name, "account", acct])['rv'] == 0
        # drive
        assert TestEnv.a2md( [ "-vv", "drive", name ] )['rv'] == 0
        self._check_md_cert([ name ])

    def test_500_104(self):
        # test case: md with one domain, TOS agreement, ACME account and authz challenge
        # setup: create md
        domain = "test500-104-" + TestDrive.dns_uniq
        name = "www." + domain
        self._prepare_md([ name ])
        assert TestEnv.apache_start() == 0
        # setup: create account on server
        run = TestEnv.a2md( ["acme", "newreg", "admin@" + domain], raw=True )
        assert run['rv'] == 0
        acct = re.match("registered: (.*)$", run["stdout"]).group(1)
        # setup: send TOS agreement to server
        assert TestEnv.a2md(["--terms", TestEnv.ACME_TOS, "acme", "agree", acct])['rv'] == 0
        # setup: link md to account
        assert TestEnv.a2md([ "update", name, "account", acct])['rv'] == 0
        # setup: create authz resource, write it into store
        run = TestEnv.a2md( ["-vv", "acme", "authz", acct, name], raw=True )
        assert run['rv'] == 0
        authz_url = re.match("authz: " + name + " (.*)$", run["stdout"]).group(1)
        # TODO: find storage-independent way to modify local authz data
        TestEnv.authz_save(name, json.dumps({
            "account": acct,
            "authorizations": [{
                "domain": name,
                "location": authz_url,
                "state": 0
            }]
            }, indent=2))
        # drive
        assert TestEnv.a2md( [ "-vv", "drive", name ] )['rv'] == 0
        self._check_md_cert([ name ])

    def test_500_105(self):
        # test case: md with one domain, local TOS agreement and ACME account that is deleted (!) on server
        # setup: create md
        domain = "test500-105-" + TestDrive.dns_uniq
        name = "www." + domain
        self._prepare_md([ name ])
        assert TestEnv.apache_start() == 0
        # setup: create account on server
        run = TestEnv.a2md( ["acme", "newreg", "test@" + domain], raw=True )
        assert run['rv'] == 0
        acct = re.match("registered: (.*)$", run["stdout"]).group(1)
        # setup: link md to account
        assert TestEnv.a2md([ "update", name, "account", acct])['rv'] == 0
        # setup: delete account on server
        assert TestEnv.a2md( ["acme", "delreg", acct] )['rv'] == 0
        # drive
        run = TestEnv.a2md( [ "drive", name ] )
        print run["stderr"]
        assert run['rv'] == 0
        self._check_md_cert([ name ])

    def test_500_106(self):
        # test case: drive using HTTPS only challenge
        domain = "test500-106-" + TestDrive.dns_uniq
        name = "www." + domain
        self._prepare_md([ name, "test." + domain ])
        assert TestEnv.apache_start() == 0
        # drive
        assert TestEnv.a2md( [ "-vv", "drive", "-c", "tls-sni-01", name ] )['rv'] == 0
        self._check_md_cert([ name, "test." + domain ])

    def test_500_107(self):
        # test case: drive again on COMPLETE md, then drive --force
        # setup: prepare md in store
        domain = "test500-107-" + TestDrive.dns_uniq
        name = "www." + domain
        self._prepare_md([ name ])
        assert TestEnv.apache_start() == 0
        # drive
        assert TestEnv.a2md( [ "-vv", "drive", name ] )['rv'] == 0
        self._check_md_cert([ name ])
        orig_cert = CertUtil(TestEnv.path_domain_pubcert(name))

        # drive again
        assert TestEnv.a2md( [ "-vv", "drive", name ] )['rv'] == 0
        self._check_md_cert([ name ])
        cert = CertUtil(TestEnv.path_domain_pubcert(name))
        # check: cert not changed
        assert cert.get_serial() == orig_cert.get_serial()

        # drive --force
        assert TestEnv.a2md( [ "-vv", "drive", "--force", name ] )['rv'] == 0
        self._check_md_cert([ name ])
        cert = CertUtil(TestEnv.path_domain_pubcert(name))
        # check: cert not changed
        assert cert.get_serial() != orig_cert.get_serial()
        # check: previous cert was archived
        cert = CertUtil(TestEnv.path_domain_pubcert( name, archiveVersion=2 ))
        assert cert.get_serial() == orig_cert.get_serial()

    def test_500_108(self):
        # test case: drive via HTTP proxy
        domain = "test500-108-" + TestDrive.dns_uniq
        name = "www." + domain
        self._prepare_md([ name ])
        assert TestEnv.apache_restart() == 0

        # drive it, with wrong proxy url -> FAIL
        r = TestEnv.a2md( [ "-p", "http://%s:1" % TestEnv.HTTPD_HOST, "drive", name ] )
        assert r['rv'] == 1
        assert "Connection refused" in r['stderr']

        # drive it, working proxy url -> SUCCESS
        assert TestEnv.a2md( [ "-p", "http://%s:%s" % (TestEnv.HTTPD_HOST, TestEnv.HTTP_PROXY_PORT), "drive", name ] )['rv'] == 0
        self._check_md_cert([ name ])

    def test_500_109(self):
        # test case: redirect on SSL-only domain
        # setup: prepare config
        if not TestEnv.httpd_is_at_least("2.5.0"):
            return
        domain = "test500-109-" + TestDrive.dns_uniq
        name = "www." + domain
        conf = HttpdConf( TestDrive.TMP_CONF )
        conf.add_admin( "admin@" + domain )
        conf.add_drive_mode( "manual" )
        conf.add_md( [name] )
        conf._add_line("  SSLEngine *:" + TestEnv.HTTPS_PORT)
        conf.add_vhost(TestEnv.HTTPS_PORT + " *:" + TestEnv.HTTP_PORT, name, aliasList=[], docRoot="htdocs/test", withSSL=False)
        conf.install()
        # setup: create resource files
        self._write_res_file(os.path.join(TestEnv.APACHE_HTDOCS_DIR, "test"), "name.txt", name)
        self._write_res_file(os.path.join(TestEnv.APACHE_HTDOCS_DIR), "name.txt", "example.org")
        assert TestEnv.apache_restart() == 0

        # drive it
        assert TestEnv.a2md( [ "drive", name ] )['rv'] == 0
        assert TestEnv.apache_restart() == 0
        # test HTTP access - no redirect
        assert TestEnv.get_content("example.org", "/name.txt", useHTTPS=False) == "example.org"
        assert TestEnv.get_content(name, "/name.txt", useHTTPS=False) == name
        r = TestEnv.get_meta(name, "/name.txt", useHTTPS=False)
        assert int(r['http_headers']['Content-Length']) == len(name)
        assert "Location" not in r['http_headers']
        # test HTTPS access
        assert TestEnv.get_content(name, "/name.txt", useHTTPS=True) == name

        # test HTTP access again -> redirect to default HTTPS port
        conf.add_require_ssl("temporary")
        conf.install()
        assert TestEnv.apache_restart() == 0
        r = TestEnv.get_meta(name, "/name.txt", useHTTPS=False)
        assert r['http_status'] == 302
        expLocation = "https://%s/name.txt" % name
        assert r['http_headers']['Location'] == expLocation
        # should not see this
        assert not 'Strict-Transport-Security' in r['http_headers']
        # test default HTTP vhost -> still no redirect
        assert TestEnv.get_content("example.org", "/name.txt", useHTTPS=False) == "example.org"
        r = TestEnv.get_meta(name, "/name.txt", useHTTPS=True)
        # also not for this
        assert not 'Strict-Transport-Security' in r['http_headers']

        # test HTTP access again -> redirect permanent
        conf.add_require_ssl("permanent")
        conf.install()
        assert TestEnv.apache_restart() == 0
        r = TestEnv.get_meta(name, "/name.txt", useHTTPS=False)
        assert r['http_status'] == 301
        expLocation = "https://%s/name.txt" % name
        assert r['http_headers']['Location'] == expLocation
        assert not 'Strict-Transport-Security' in r['http_headers']
        # should see this
        r = TestEnv.get_meta(name, "/name.txt", useHTTPS=True)
        assert r['http_headers']['Strict-Transport-Security'] == 'max-age=15768000'

    def test_500_110(self):
        # test case: SSL-only domain, override headers generated by mod_md 
        # setup: prepare config
        if not TestEnv.httpd_is_at_least("2.5.0"):
            return
        domain = "test500-110-" + TestDrive.dns_uniq
        name = "www." + domain
        conf = HttpdConf( TestDrive.TMP_CONF )
        conf.add_admin( "admin@" + domain )
        conf.add_drive_mode( "manual" )
        conf.add_require_ssl("permanent")
        conf.add_md( [name] )
        conf._add_line("  SSLEngine *:" + TestEnv.HTTPS_PORT)
        conf.add_vhost(TestEnv.HTTPS_PORT + " *:" + TestEnv.HTTP_PORT, name, aliasList=[], withSSL=False)
        conf.install()
        assert TestEnv.apache_restart() == 0
        # drive it
        assert TestEnv.a2md( [ "drive", name ] )['rv'] == 0
        assert TestEnv.apache_restart() == 0

        # test override HSTS header
        conf._add_line('  Header set Strict-Transport-Security "max-age=10886400; includeSubDomains; preload"')
        conf.install()
        assert TestEnv.apache_restart() == 0
        r = TestEnv.get_meta(name, "/name.txt", useHTTPS=True)
        assert r['http_headers']['Strict-Transport-Security'] == 'max-age=10886400; includeSubDomains; preload'

        # test override Location header
        conf._add_line('  Redirect /a /name.txt')
        conf._add_line('  Redirect seeother /b /name.txt')
        conf.install()
        assert TestEnv.apache_restart() == 0
        # check: default redirect by mod_md still works
        expLocation = "https://%s/name.txt" % name
        r = TestEnv.get_meta(name, "/name.txt", useHTTPS=False)
        assert r['http_status'] == 301
        assert r['http_headers']['Location'] == expLocation
        # check: redirect as given by mod_alias
        expLocation = "https://%s/a" % name
        r = TestEnv.get_meta(name, "/a", useHTTPS=False)
        assert r['http_status'] == 301                          # FAIL: mod_alias generates Location header instead of mod_md
        assert r['http_headers']['Location'] == expLocation

    def test_500_111(self):
        # test case: vhost with parallel HTTP/HTTPS, check mod_alias redirects
        # setup: prepare config
        if not TestEnv.httpd_is_at_least("2.5.0"):
            return
        domain = "test500-111-" + TestDrive.dns_uniq
        name = "www." + domain
        conf = HttpdConf( TestDrive.TMP_CONF )
        conf.add_admin( "admin@" + domain )
        conf.add_drive_mode( "manual" )
        conf.add_md( [name] )
        conf._add_line("  LogLevel alias:debug")
        conf._add_line("  SSLEngine *:" + TestEnv.HTTPS_PORT)
        conf.start_vhost(TestEnv.HTTPS_PORT + " *:" + TestEnv.HTTP_PORT, name, aliasList=[], withSSL=False)
        conf.end_vhost()
        conf.install()
        assert TestEnv.apache_restart() == 0
        # drive it
        assert TestEnv.a2md( [ "drive", name ] )['rv'] == 0
        assert TestEnv.apache_restart() == 0

        # setup: place redirect rules
        conf._add_line('  Redirect /a /name.txt')
        conf._add_line('  Redirect seeother /b /name.txt')
        conf.install()
        assert TestEnv.apache_restart() == 0
        # check: redirects on HTTP
        expLocation = "http://%s:%s/name.txt" % (name, TestEnv.HTTP_PORT)
        r = TestEnv.get_meta(name, "/a", useHTTPS=False)
        assert r['http_status'] == 302
        assert r['http_headers']['Location'] == expLocation
        r = TestEnv.get_meta(name, "/b", useHTTPS=False)
        assert r['http_status'] == 303
        assert r['http_headers']['Location'] == expLocation
        # check: redirects on HTTPS
        expLocation = "https://%s:%s/name.txt" % (name, TestEnv.HTTPS_PORT)
        r = TestEnv.get_meta(name, "/a", useHTTPS=True)
        assert r['http_status'] == 302
        assert r['http_headers']['Location'] == expLocation     # FAIL: expected 'https://...' but found 'http://...'
        r = TestEnv.get_meta(name, "/b", useHTTPS=True)
        assert r['http_status'] == 303
        assert r['http_headers']['Location'] == expLocation


    # --------- critical state change -> drive again ---------

    def test_500_200(self):
        # test case: add dns name on existing valid md
        # setup: create md in store
        domain = "test500-200-" + TestDrive.dns_uniq
        name = "www." + domain
        self._prepare_md([ name ])
        assert TestEnv.apache_start() == 0
        # setup: drive it
        assert TestEnv.a2md( [ "drive", name ] )['rv'] == 0
        old_cert = CertUtil(TestEnv.path_domain_pubcert(name))
        # setup: add second domain
        assert TestEnv.a2md([ "update", name, "domains", name, "test." + domain ])['rv'] == 0
        # drive
        assert TestEnv.a2md( [ "-vv", "drive", name ] )['rv'] == 0
        # check new cert
        self._check_md_cert([ name, "test." + domain ])
        new_cert = CertUtil(TestEnv.path_domain_pubcert(name))
        assert old_cert.get_serial() != new_cert.get_serial()

    @pytest.mark.parametrize("renewWindow,testDataList", [
        ("14d", [
            { "valid": { "notBefore": -5,   "notAfter": 180 }, "renew" : False }, 
            { "valid": { "notBefore": -200, "notAfter": 15  }, "renew" : False },
            { "valid": { "notBefore": -200, "notAfter": 13  }, "renew" : True },
        ]),
        ("30%", [
            { "valid": { "notBefore": -0,   "notAfter": 180 }, "renew" : False },
            { "valid": { "notBefore": -120, "notAfter": 60  }, "renew" : False },
            { "valid": { "notBefore": -126, "notAfter": 53  }, "renew" : True },
        ])
    ])
    def test_500_201(self, renewWindow, testDataList):
        # test case: trigger cert renew when entering renew window 
        # setup: prepare COMPLETE md
        domain = "test500-201-" + TestDrive.dns_uniq
        name = "www." + domain
        conf = HttpdConf( TestDrive.TMP_CONF )
        conf.add_admin( "admin@" + domain )
        conf.add_drive_mode( "manual" )
        conf.add_renew_window( renewWindow )
        conf.add_md( [name] )
        conf.install()
        assert TestEnv.apache_restart() == 0
        assert TestEnv.a2md([ "list", name])['jout']['output'][0]['state'] == TestEnv.MD_S_INCOMPLETE
        # setup: drive it
        assert TestEnv.a2md( [ "drive", name ] )['rv'] == 0
        cert1 = CertUtil(TestEnv.path_domain_pubcert(name))
        assert TestEnv.a2md([ "list", name ])['jout']['output'][0]['state'] == TestEnv.MD_S_COMPLETE

        # replace cert by self-signed one -> check md status
        print "TRACE: start testing renew window: %s" % renewWindow
        for tc in testDataList:
            print "TRACE: create self-signed cert: %s" % tc["valid"]
            CertUtil.create_self_signed_cert( [name], tc["valid"])
            cert2 = CertUtil(TestEnv.path_domain_pubcert(name))
            assert cert2.get_serial() != cert1.get_serial()
            md = TestEnv.a2md([ "list", name ])['jout']['output'][0]
            assert md["renew"] == tc["renew"], \
                "Expected renew == {} indicator in {}, test case {}".format(tc["renew"], md, tc)

    @pytest.mark.parametrize("keyType,keyParams,expKeyLength", [
        ( "RSA", [ 2048 ], 2048 ),
        ( "RSA", [ 3072 ], 3072),
        ( "RSA", [ 4096 ], 4096 ),
        ( "Default", [ ], 2048 )
    ])
    def test_500_202(self, keyType, keyParams, expKeyLength):
        # test case: specify RSA key length and verify resulting cert key 
        # setup: prepare md
        domain = "test500-202-" + TestDrive.dns_uniq
        name = "www." + domain
        conf = HttpdConf( TestDrive.TMP_CONF )
        conf.add_admin( "admin@" + domain )
        conf.add_drive_mode( "manual" )
        conf.add_private_key(keyType, keyParams)
        conf.add_md( [name] )
        conf.install()
        assert TestEnv.apache_restart() == 0
        assert TestEnv.a2md([ "list", name])['jout']['output'][0]['state'] == TestEnv.MD_S_INCOMPLETE
        # setup: drive it
        assert TestEnv.a2md( [ "-vv", "drive", name ] )['rv'] == 0, \
            "Expected drive to succeed for MDPrivateKeys {} {}".format(keyType, keyParams)
        assert TestEnv.a2md([ "list", name ])['jout']['output'][0]['state'] == TestEnv.MD_S_COMPLETE
        # check cert key length
        cert = CertUtil(TestEnv.path_domain_pubcert(name))
        assert cert.get_key_length() == expKeyLength

    def test_500_203(self):
        # test case: reproduce issue with initially wrong agreement URL
        domain = "test500-203-" + TestDrive.dns_uniq
        name = "www." + domain
        # setup: prepare md with invalid TOS url
        conf = HttpdConf( TestDrive.TMP_CONF, acmeTos=TestEnv.ACME_TOS2 )
        conf.add_admin( "admin@" + domain )
        conf.add_drive_mode( "manual" )
        conf.add_md( [name] )
        conf.install()
        assert TestEnv.apache_restart() == 0
        assert TestEnv.a2md([ "list", name])['jout']['output'][0]['state'] == TestEnv.MD_S_INCOMPLETE
        # drive it -> fail after account registration
        assert TestEnv.a2md( [ "-vv", "drive", name ] )['rv'] == 1

        # adjust config: replace TOS url with correct one
        conf = HttpdConf( TestDrive.TMP_CONF )
        conf.add_admin( "admin@" + domain )
        conf.add_drive_mode( "manual" )
        conf.add_md( [name] )
        conf.install()
        time.sleep(1)
        assert TestEnv.apache_restart() == 0
        assert TestEnv.a2md([ "list", name])['jout']['output'][0]['state'] == TestEnv.MD_S_INCOMPLETE
        # drive it -> runs OK
        assert TestEnv.a2md( [ "-vv", "drive", name ] )['rv'] == 0
        assert TestEnv.a2md([ "list", name])['jout']['output'][0]['state'] == TestEnv.MD_S_COMPLETE


    # --------- non-critical state change -> keep data ---------

    def test_500_300(self):
        # test case: remove one domain name from existing valid md
        # setup: create md in store
        domain = "test500-300-" + TestDrive.dns_uniq
        name = "www." + domain
        self._prepare_md([ name, "test." + domain, "xxx." + domain ])
        assert TestEnv.apache_start() == 0
        # setup: drive it
        assert TestEnv.a2md( [ "drive", name ] )['rv'] == 0
        old_cert = CertUtil(TestEnv.path_domain_pubcert(name))
        # setup: remove one domain
        assert TestEnv.a2md([ "update", name, "domains"] + [ name, "test." + domain ])['rv'] == 0
        # drive
        assert TestEnv.a2md( [ "-vv", "drive", name ] )['rv'] == 0
        # compare cert serial
        new_cert = CertUtil(TestEnv.path_domain_pubcert(name))
        assert old_cert.get_serial() == new_cert.get_serial()

    def test_500_301(self):
        # test case: change contact info on existing valid md
        # setup: create md in store
        domain = "test500-301-" + TestDrive.dns_uniq
        name = "www." + domain
        self._prepare_md([ name ])
        assert TestEnv.apache_start() == 0
        # setup: drive it
        assert TestEnv.a2md( [ "drive", name ] )['rv'] == 0
        old_cert = CertUtil(TestEnv.path_domain_pubcert(name))
        # setup: add second domain
        assert TestEnv.a2md([ "update", name, "contacts", "test@" + domain ])['rv'] == 0
        # drive
        assert TestEnv.a2md( [ "drive", name ] )['rv'] == 0
        # compare cert serial
        new_cert = CertUtil(TestEnv.path_domain_pubcert(name))
        assert old_cert.get_serial() == new_cert.get_serial()

    # --------- network problems ---------

    def test_500_400(self):
        # test case: server not reachable
        domain = "test500-400" + TestDrive.dns_uniq
        name = "www." + domain
        self._prepare_md([ name ])
        assert TestEnv.a2md(
            [ "update", name, "ca", "http://localhost:4711/directory"]
            )['rv'] == 0
        # drive
        run = TestEnv.a2md( [ "drive", name ] )
        assert run['rv'] == 1
        assert run['jout']['status'] != 0
        assert run['jout']['description'] == 'Connection refused'

    # --------- _utils_ ---------

    def _prepare_md(self, dnsList):
        assert TestEnv.a2md(["add"] + dnsList)['rv'] == 0
        assert TestEnv.a2md(
            [ "update", dnsList[0], "contacts", "admin@" + dnsList[0] ]
            )['rv'] == 0
        assert TestEnv.a2md( 
            [ "update", dnsList[0], "agreement", TestEnv.ACME_TOS ]
            )['rv'] == 0

    def _write_res_file(self, docRoot, name, content):
        if not os.path.exists(docRoot):
            os.makedirs(docRoot)
        open(os.path.join(docRoot, name), "w").write(content)

    def _check_md_cert(self, dnsList):
        name = dnsList[0]
        md = TestEnv.a2md([ "list", name ])['jout']['output'][0]
        # check tos agreement, cert url
        assert md['state'] == TestEnv.MD_S_COMPLETE
        assert md['ca']['agreement'] == TestEnv.ACME_TOS
        assert "url" in md['cert']

        # check private key, validate certificate
        # TODO: find storage-independent way to read local certificate
        # md_store = json.loads( open( TestEnv.path_store_json(), 'r' ).read() )
        # encryptKey = md_store['key']
        # print "key (%s): %s" % ( type(encryptKey), encryptKey )
        CertUtil.validate_privkey(TestEnv.path_domain_privkey(name))
        cert = CertUtil( TestEnv.path_domain_pubcert(name) )
        cert.validate_cert_matches_priv_key( TestEnv.path_domain_privkey(name) )

        # check SANs and CN
        assert cert.get_cn() == name
        # compare sets twice in opposite directions: SAN may not respect ordering
        sanList = cert.get_san_list()
        assert len(sanList) == len(dnsList)
        assert set(sanList).issubset(dnsList)
        assert set(dnsList).issubset(sanList)
        # check valid dates interval
        notBefore = cert.get_not_before()
        notAfter = cert.get_not_after()
        assert notBefore < datetime.now(notBefore.tzinfo)
        assert notAfter > datetime.now(notAfter.tzinfo)
        # compare cert with resource on server
        server_cert = CertUtil( md['cert']['url'] )
        assert cert.get_serial() == server_cert.get_serial()

    RE_MSG_OPENSSL_BAD_DECRYPT = re.compile('.*\'bad decrypt\'.*')

    def _check_account_key(self, name):
        # read encryption key
        md_store = json.loads( open( TestEnv.path_store_json(), 'r' ).read() )
        encryptKey = base64.urlsafe_b64decode( str(md_store['key']) )
        # check: key file is encrypted PEM
        md = TestEnv.a2md([ "list", name ])['jout']['output'][0]
        acc = md['ca']['account']
        CertUtil.validate_privkey(TestEnv.path_account_key( acc ), lambda *args: encryptKey )

	# sei: also deactivated, does not work under *NIX
        # check: negative test with wrong key - pyOpenSSL loads without error, if the file is unencrypted
        #encryptKey = base64.urlsafe_b64decode( str("dJRvw9dkigC1dmVekPaN08DWaXfQ24IL17wUSWq2C_U5FBzSGOb6oQO-_yTGzPC4") )
        #with pytest.raises(Exception) as ex:
        #    CertUtil.validate_privkey(TestEnv.path_account_key( acc ), encryptKey)
        #assert TestDrive.RE_MSG_OPENSSL_BAD_DECRYPT.match( str(ex.value) )
