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
cdir    = os.path.realpath(os.path.dirname(os.path.abspath(sys.argv[0])))
filename = os.path.join(cdir, 'config.xml')
formats = ('mkv','mp4','avi','wmv','flv','mov')
ep_pat  = f'(?<=/)?[^/]*?(\\d+)x(\\d+)[^/]*?\\.({"|".join(formats)})$'
ep_pat  = re.compile(ep_pat, re.I)

readline.parse_and_bind("tab: complete")
readline.set_completer_delims(' ')

def list_completion(values, text, state=-1):
  values = [f for f in values if f.startswith(text)]
  return values[state]

def file_completion(sftp, text, state=-1):
  dir = os.path.dirname(text) or '.'
  if sftp:
    files = [dir+'/'+f if dir!='.' else f for f in sftp.listdir(dir)]
    files = [f+'/' for f in files if sftp.isdir(f)]
  else:
    files = [os.path.join(dir, f) if dir!='.' else f for f in os.listdir(dir)]
    files = [f+os.path.sep for f in files if os.path.isdir(f)]
  files=[f for f in files if f.startswith(text)]

  return files if state == -1 else files[state]

local_completion = lambda text, state: file_completion(None, text, state)

def emby_connect(config):
  embycfg = config.find('.//emby')
  if embypy and embycfg is not None:
    conn = embypy.Emby(**embycfg.attrib)
    embycfg.set('token',  conn.connector.token or conn.connector.api_key)
    embycfg.set('userid', conn.connector.userid)
    return conn
  return None

def get_connection(config):
  cnopts = pysftp.CnOpts()
  cnopts.hostkeys = None
  remote_root = '/mnt/5TB_share/sftp-root/Emby/Anime_Symlinks/'
  remote_root = config.findtext('.//root') or remote_root
  return pysftp.Connection(config.findtext('.//hostname'),
                  port=int(config.findtext('.//port')),
                  username=config.findtext('.//username'),
                  password=config.findtext('.//password') or None,
                  private_key=config.findtext('.//key') or None,
                  private_key_pass=config.findtext('.//password') or None,
                  default_path=remote_root or None,
                  cnopts=cnopts,
  )

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

  with get_connection(config) as sftp:
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
  conn = emby_connect(config)
  with get_connection(config) as sftp:
    for group in config.findall('./group'):
      save_location = group.get('location', './')
      for show in group.findall('./show'):
        process_show_config(show, save_location, sftp, conn)

def get_emby_obj(path, conn=None):
  if conn is None:
    return None
  for obj in conn.series_sync + conn.movies_sync:
    if obj.path in path or path.lower() in obj.path.lower():
      return obj
  return None

def process_show_config(config, save_location, sftp, conn=None, ir=False):
  ranges   = xml_range_to_dict(config)
  showpath = config.findtext('.//remotepath')
  process_show(config, showpath, save_location, sftp, conn, ranges, ir)

def update_emby_info(conn, showpath, ranges):
  if conn is None:
    return
  item = get_emby_obj(showpath, conn)
  try:
    for season in item.seasons_sync:
      eps = ranges.get(season.index_number, set())
      for ep in season.episodes_sync:
        if ep.index_number in eps and not ep.watched:
          ep.setWatched_sync()
  except:
    try:
      item.setWatched_sync()
    except:
      return

def process_show(config, showpath, save_location, sftp,
                 conn=None, ranges={}, ir=False):
  pfile   = lambda path: process_file(ranges, save_location, sftp, path, ir)
  ignore = lambda x: None
  sftp.walktree(showpath, pfile, ignore, ignore)
  if config is not None:
    update_range(config, ranges)
  update_emby_info(conn, showpath, ranges)

def download_item(config, item_name):
  conn = emby_connect(config)
  sloc = config.xpath('.//group/@location') or ['./']
  sloc = sloc[0]
  with get_connection(config) as sftp:
    if not sftp.exists(item_name):
      if conn:
        return download_search(config, sloc, item_name, sftp, conn)
      else:
        return None
    elif sftp.isdir(item_name):
      return download_dir(config, sloc, item_name, sftp, conn)
    elif sftp.isfile(item_name):
      return download_file(config, sloc, item_name, sftp, conn)

def download_search(config, save_location, path, sftp, conn):
  pass

def download_dir(config, save_location, path, sftp, conn):
  for showcfg in config.xpath('.//show'):
    show_path = showcfg.findtext('./remotepath')
    if path in show_path or show_path in path:
      save_location = showcfg.getparent().get('location')
      process_show_config(showcfg, save_location, sftp, conn, ir=True)
      break
  else:
    process_show(None, path, save_location, sftp, conn)

def download_file(config, save_location, path, sftp, conn):
  if not sftp.exists(path):
    return
  if path.lower().rpartition('.')[2] in formats:
    ranges = {}
    process_file(ranges, save_location, sftp, path)
    update_emby_info(conn, path, ranges)
  else:
    with sftp.open(path) as f:
      for line in f.readlines():
        download_file(config, save_location, line.strip(), sftp, conn)

def process_file(ranges, save_location, sftp, path, ir=False):
  if path.rpartition('.')[2].lower() not in formats:
    return

  info = ep_pat.search(path)
  if info:
    season, episode = int(info.group(1)), int(info.group(2))

  name = os.path.basename(path)
  size = 70 - len(name)

  lpath = os.path.join(save_location, name)
  local_size  = os.stat(lpath).st_size if os.path.exists(lpath) else 0
  remote_size = sftp.lstat(path).st_size
  if local_size == remote_size:
    # file already fully downloaded, skip
    return

  def callback(cur, tot):
    out = f'\r{name} [{"="*(size*cur//tot)}{" "*(size-size*cur//tot)}]      '
    if cur == tot:
      print(out)
    else:
      print(out, end='\r')

  if not info or ir or episode not in ranges.get(season, set()):
    if info:
      ranges[season] = ranges.get(season, set()).union({episode})
    sftp.get(path,
      localpath=os.path.join(save_location, name),
      callback=callback,
    )

if __name__ == '__main__':
  config = load()
  for i,arg in enumerate(sys.argv):
    if i==0: continue
    if arg.lower() in ('edt', 'edit'):
      config = edit_config(config)
    elif arg.lower() in ('l', 'ls', 'lst', 'list'):
      with get_connection(config) as sftp:
        print('\n'.join(file_completion(sftp, ' '.join(sys.argv[i+1:]), -1)))
      break
    else:
      download_item(config, arg)
      break
  else:
    process_config(config)
  save(config)
