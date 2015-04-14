#!/usr/bin/python

import apt
import ConfigParser
import os
import subprocess
import sys
import urllib2


sys.path.insert(0, os.path.join(os.environ['CHARM_DIR'], 'lib'))

from charmhelpers.core import (
    hookenv,
    host,
)
from charmhelpers.core.services import RelationContext

hooks = hookenv.Hooks()
log = hookenv.log
config = hookenv.config()
config.implicit_save = False

APT_SOURCES_LIST = '/etc/apt/sources.list.d/beaver.list'
SERVICE = 'beaver'
KEYURL = 'http://keyserver.ubuntu.com:11371/pks/lookup?' \
         'op=get&search=0xA65E2E5D742A38EE'
SOURCE = 'deb http://ppa.launchpad.net/evarlast/experimental/ubuntu trusty main'
DEPENDENCIES = ('beaver', )
BEAVER_CONFIG = '/etc/beaver/conf'


def ensure_packages(*pkgs):
    '''
    ensure_packages installs and upgrades pacakges. The goal is to be apt-get
    install equivalent.
    '''
    apt.apt_pkg.config['APT::Install-Recommends'] = '0'
    apt.apt_pkg.config['APT::Get::Assume-Yes'] = '1'
    cache = apt.Cache()
    for name in pkgs:
        pkg = cache[name]
        if not pkg.is_installed:
            pkg.mark_install()
        if pkg.is_upgradable:
            pkg.mark_upgrade()
    cache.commit()


@hooks.hook('config-changed')
def config_changed():
    config = hookenv.config()

    for key in config:
        if config.changed(key):
            log("config['{}'] changed from {} to {}".format(
                key, config.previous(key), config[key]))

    config.save()
    start()


@hooks.hook('install')
def install():
    log('Installing beaver')
    ensure_ppa()
    apt_get_update()
    ensure_packages(*DEPENDENCIES)


@hooks.hook('start')
def start():
    host.service_restart(SERVICE) or host.service_start(SERVICE)


def restart():
    log('(re)starting ' + SERVICE)
    host.service_restart(SERVICE) or \
        host.service_start(SERVICE)


@hooks.hook('stop')
def stop():
    host.service_stop(SERVICE)


@hooks.hook('upgrade-charm')
def upgrade_charm():
    log('Upgrading beaver')
    apt_get_update()
    ensure_packages(*DEPENDENCIES)
    restart()


@hooks.hook('logs-relation-joined')
@hooks.hook('logs-relation-changed')
def logs_relation_changed():
    log('Logs changed')
    logs_relation_data = logs_relation()
    if logs_relation_data is not None:
        write_beaver_config(logs_relation_data)
        restart()


@hooks.hook('input-tcp-relation-joined')
@hooks.hook('input-tcp-relation-changed')
def input_tcp_relation_changed():
    log('Input tcp changed')
    private_ip, port = input_tcp_relation()
    write_beaver_config_forlogstash(private_ip, port)
    restart()


def write_beaver_config(logs_relation_data):
    config = get_config()
    for file, type in logs_relation_data:
        if not config.has_section(file):
            config.add_section(file)
        config.set(file, 'type', type)
    if not config.has_section('beaver'):
        config.add_section('beaver')
    config.set('beaver', 'logstash_version', 1)
    with open(BEAVER_CONFIG, "wb") as config_file:
        config.write(config_file)


def write_beaver_config_forlogstash(private_ip, port):
    config = ConfigParser.ConfigParser()
    if not config.has_section('beaver'):
        config.add_section('beaver')
    config.set('beaver', 'tcp_host', private_ip)
    config.set('beaver', 'tcp_port', port)
    with open(BEAVER_CONFIG, "wb") as config_file:
        config.write(config_file)


def get_config():
    config = ConfigParser.ConfigParser()
    if not os.path.isfile(BEAVER_CONFIG):
        return config
    config.read(BEAVER_CONFIG)
    return config


def logs_relation():
    lsr = LogsRelation()
    log("LogsRelation: {}".format(lsr))
    r = lsr['logs']
    if not r or 'types' not in r[0]:
        return None
    if not r or 'files' not in r[0]:
        return None
    types = r[0]['types'].split()
    files = r[0]['files'].split()
    return zip(types, files)


def input_tcp_relation():
    itr = InputTcpRelation()
    log("InputTcpRelation: {}".format(itr))
    r = itr['input-tcp']
    if not r or 'port' not in r[0]:
        return None
    if not r or 'private-address' not in r[0]:
        return None
    port = r[0]['port']
    private_address = r[0]['private-address']
    return private_address, port


def ensure_ppa():
    if not has_source_list():
        apt_key_add(KEYURL)
        add_source_list()


def add_source_list():
    host.write_file(APT_SOURCES_LIST, SOURCE + "\n")


def has_source_list():
    if not os.path.exists(APT_SOURCES_LIST):
        return False
    return (
        open(APT_SOURCES_LIST, 'r').read().strip()
        in SOURCE
    )


def apt_key_add(keyurl):
    r = urllib2.urlopen(keyurl)
    data = r.read()
    PIPE = subprocess.PIPE
    proc = subprocess.Popen(('apt-key', 'add', '-'),
                            stdin=PIPE, stdout=PIPE, stderr=PIPE)
    out, err = proc.communicate(input=data)
    if out != 'OK\n'or err != '':
        log("error running apt-key add:" + out + err)


def apt_get_update():
    apt.apt_pkg.config['APT::Install-Recommends'] = '0'
    cache = apt.Cache()
    try:
        cache.update()
        cache.open(None)
        cache.commit()
    except Exception as e:
        msg = "apt_get_update error:{}".format(e)
        log(msg)


class LogsRelation(RelationContext):
    name = 'logs'
    interface = 'logs'
    required_keys = ['types', 'files']


class InputTcpRelation(RelationContext):
    name = 'input-tcp'
    interface = 'logstash-tcp'
    required_keys = ['port', 'private-address']


if __name__ == "__main__":
    # execute a hook based on the name the program is called by
    hooks.execute(sys.argv)
