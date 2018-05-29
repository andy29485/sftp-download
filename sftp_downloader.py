#!/usr/bin/env python3

# Installation:
#   sudo pip3 install pysftp lxml bisect
# or
#   python3 -m pip install pysftp lxml bisect

'''
<config>
  <connection>
    <auth>
      <hostname>...</hostname>
      <port>...</port>
      <username>...</username>
      <password>...</password>
      <key>...</key>
    </auth>
    <group location="/home/az">
      <show>
        <remotepath>...</remotepath>
        <downloaded>
          <range season="..." start="..." end="..." />
        </downloaded>
      </show>
      ...
    </group>
    ...
  </connection>
</config>
'''

import pysftp
import bisect
import os
import sys
import re
from lxml import etree

try:
  import embypy
except:
  embypy = None

try:
  import readline
except:
  try:
    import pyreadline as readline
  except:
    print('please install readline or pyreadline (windows) for tab completion')


# globals
cdir = os.path.realpath(os.path.dirname(os.path.abspath(sys.argv[0])))
filename = os.path.join(cdir, 'config.xml')
ep_pat = '(?<=/)?[^/]*?(\d+)x(\d+)[^/]*?\\.(mkv|mp4|avi|wmv|flv|mov)$'
ep_pat = re.compile(ep_pat, re.I)

readline.parse_and_bind("tab: complete")
readline.set_completer_delims(' ')

def list_completion(values, text, state):
  values = [f for f in values if f.startswith(text)]
  return values[state]

def file_completion(sftp, text, state):
  dir = os.path.dirname(text) or '.'
  if sftp:
    files = [dir+'/'+f if dir!='.' else f for f in sftp.listdir(dir)]
    files = [f+'/' for f in files if sftp.isdir(f)]
  else:
    files = [os.path.join(dir, f) if dir!='.' else f for f in os.listdir(dir)]
    files = [f+os.path.sep for f in files if os.path.isdir(f)]
  files=[f for f in files if f.startswith(text)]

  return files[state]

local_completion = lambda text, state: file_completion(None, text, state)

def edit_config(config=None):
  if config is None:
    config = etree.Element('config')

  conn = config.find('./connection')
  if conn is None:
    conn = etree.SubElement(config, 'connection')

  auth = config.find('./connection/auth')
  if auth is None:
    auth = etree.SubElement(conn, 'auth')

    hostname = etree.SubElement(auth, 'hostname')
    port     = etree.SubElement(auth, 'port')
    username = etree.SubElement(auth, 'username')
    pkeyfile = etree.SubElement(auth, 'key')
    password = etree.SubElement(auth, 'password')

    hostname.text = input('Please enter hostname:                  ')
    port.text     = input('Please enter port [opt]:                ') or '22'
    username.text = input('Please enter username:                  ')
    password.text = input('Please enter password [opt]:            ')
    readline.set_completer(local_completion)
    pkeyfile.text = input('Please enter path to private key [opt]: ')
    pkeyfile.text = pkeyfile.text and os.path.realpath(pkeyfile.text)
    readline.set_completer(None)

  readline.set_completer(local_completion)
  dirname = os.path.realpath(input('\nPlease enter local [save] dir: '))
  readline.set_completer(None)

  loc = conn.find(f'./group[@location="{dirname}"]')
  if loc is None:
    loc = etree.SubElement(conn, 'group')
    loc.set('location', dirname)

  cnopts = pysftp.CnOpts()
  cnopts.hostkeys = None

  remote_root = '/mnt/5TB_share/sftp-root/Emby/Anime_Symlinks/'
  remote_root = auth.findtext('./root') or remote_root

  with pysftp.Connection(config.findtext('.//hostname'),
                port=int(config.findtext('.//port')),
                username=config.findtext('.//username'),
                password=config.findtext('.//password') or None,
                private_key=config.findtext('.//key') or None,
                private_key_pass=config.findtext('.//password') or None,
                default_path=remote_root,
                cnopts=cnopts,
  ) as sftp:

    comp = lambda text, state: file_completion(sftp, text, state)
    readline.set_completer(comp)
    rpath = input('Please enter remote show dir [empty to end]: ')
    readline.set_completer(None)

    while rpath:
      rpath = sftp.normalize(rpath)
      show = loc.xpath(f'./show/remotepath[text()="{rpath}"]/..')
      if not show:
        show = etree.SubElement(loc,  'show')
        path = etree.SubElement(show, 'remotepath')
        path.text = rpath
      else:
        show = show[0]

      downloaded = show.find('./downloaded')
      if downloaded is None:
        downloaded = etree.SubElement(show, 'downloaded')

      rng = True
      while rng:
        rng = input('Please enter ep range (in form `season start-end`): ')
        match = re.search(r'^(\d+)\s+(\d+)-(\d+)$', rng)
        if match:
          etree.SubElement(downloaded, 'range',
                         season=match.group(1),
                         start=match.group(2),
                         end=match.group(3),
          )

      readline.set_completer(comp)
      rpath = input('\nPlease enter remote show dir [empty to end]: ')
      readline.set_completer(None)

  save(config)
  return config

def save(config, filename=filename):
  with open(filename, 'w') as f:
    tree_str = etree.tostring(config, xml_declaration=True,
                              pretty_print=True, encoding='UTF-8'
    )
    f.write(tree_str.decode())

def load(filename=filename):
  global config
  try:
    # recover in case of minor errors
    parser = etree.XMLParser(recover=True, remove_blank_text=True)
    return etree.parse(filename, parser=parser).getroot()
  except:
    return edit_config()

def xml_range_to_dict(config):
  ranges = {}
  for rng in config.findall('./downloaded/range'):
    season  = int(rng.get('season'))
    startep = int(rng.get('start'))
    endep   = int(rng.get('end'))+1
    ranges[season] = ranges.get(season, set()).union(range(startep, endep))
  return ranges

def update_range(config, ranges):
  etree.strip_elements(config, 'range')

  downloaded = config.find('./downloaded')
  if downloaded is None:
    downloaded = etree.SubElement(config, 'downloaded')

  def add(season, start, end):
    etree.SubElement(downloaded,'range',
                     season=str(season),
                     start=str(start),
                     end=str(end)
    )

  for season, rng in ranges.items():
    rng = sorted(rng)
    end = start = rng[0]
    for i,ep in enumerate(rng[1:]):
      if ep == end+1 and i != len(rng)-2:
        end = ep
      elif ep == end+1:
        end = ep
        add(season, start, end)
      else:
        add(season, start, end)
        start = end = ep
    if start == end:
      add(season, start, end)
  return config

def process_config(config):
  for connection in config.findall('./connection'):
    process_connection(connection)

def process_connection(config):
  cnopts = pysftp.CnOpts()
  cnopts.hostkeys = None

  embycfg = config.find('.//emby')
  if embypy and embycfg is not None:
    conn = embypy.Emby(**embycfg.attrib)
    embycfg.set('token',  conn.connector.token or conn.connector.api_key)
    embycfg.set('userid', conn.connector.userid)
  else:
    conn = None

  with pysftp.Connection(config.findtext('.//hostname'),
                port=int(config.findtext('.//port')),
                username=config.findtext('.//username'),
                password=config.findtext('.//password') or None,
                private_key=config.findtext('.//key') or None,
                private_key_pass=config.findtext('.//password') or None,
                cnopts=cnopts,
  ) as sftp:
    for group in config.findall('./group'):
      save_location = group.get('location', './')
      for show in group.findall('./show'):
        process_show(show, save_location, sftp, conn)

def process_show(config, save_location, sftp, conn=None):
  ranges   = xml_range_to_dict(config)
  showpath = config.findtext('.//remotepath')
  pfile    = lambda path: process_file(config, ranges, save_location, sftp, path)
  ignore   = lambda x: None

  sftp.walktree(showpath, pfile, ignore, ignore)
  update_range(config, ranges)

  if conn:
    try:
      show = next(x for x in conn.series_sync if showpath in x.path)
    except:
      show = 0
  if show:
    for season in show.seasons_sync:
      eps = ranges.get(season.index_number, set())
      for ep in season.episodes_sync:
        if ep.index_number in eps and not ep.watched:
          ep.setWatched_sync()

def process_file(config, ranges, save_location, sftp, path):
  info = ep_pat.search(path)
  if not info:
    return

  season, episode = int(info.group(1)), int(info.group(2))
  name = os.path.basename(path)
  size = 70 - len(name)

  def callback(cur, tot):
    out = f'\r{name} [{"="*(size*cur//tot)}{" "*(size-size*cur//tot)}]      '
    if cur == tot:
      print(out)
    else:
      print(out, end='\r')

  if episode not in ranges.get(season, set()):
    ranges[season] = ranges.get(season, set()).union({episode})
    sftp.get(path,
      localpath=os.path.join(save_location, name),
      callback=callback,
    )

if __name__ == '__main__':
  config = load()
  if len(sys.argv) > 1:
    config = edit_config(config)
  process_config(config)
  save(config)
