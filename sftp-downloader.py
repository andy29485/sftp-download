#!/usr/bin/env python3

# Installation:
#   sudo pip3 install pysftp lxml bisect
# or
#   python3 -m pip install pysftp lxml bisect

import pysftp
import bisect
import shutil
import logging
import time
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
cdir     = os.path.realpath(os.path.dirname(os.path.abspath(sys.argv[0])))
filename = os.path.join(cdir, 'config.xml')
formats  = ('mkv','mp4','avi','wmv','flv','mov')
ep_pat   = f'(?<=/)?[^/]*?(\\d+)x(\\d+)[^/]*?\\.({"|".join(formats)})$'
ep_pat   = re.compile(ep_pat, re.I)
ccache   = {'remote':{}, 'local':{}}
logger   = logging.Logger('sftp_downloader')

logger.setLevel(logging.ERROR)
logger.addHandler(logging.StreamHandler(sys.stdout))

readline.parse_and_bind("tab: complete")
readline.set_completer_delims(' ')

# completion helper functions
def basename(path):
  if len(path) < 2:
    return path
  if path.endswith('/') or path.endswith(os.path.sep):
    path = path[:-1]
  return os.path.basename(path)

def list_completion(values, text, state=-1):
  values = [f for f in values if f.startswith(text)]
  return values[state]

def file_completion(sftp, emby, text, state):
  global ccache
  old = ''
  if not sftp:
    old  = text
    text = os.path.expanduser(text)

  dir = os.path.dirname(text) or '.'
  typ = 'remote' if sftp else 'local'
  sep = '/' if sftp else os.path.sep
  files = []

  if sftp:
    norm = sftp.normalize(dir)
  else:
    norm = os.path.abspath(dir)

  def join(a, b):
    if sftp:
      return a+'/'+b
    return os.path.join(a,b)

  def lsdir(d):
    return (sftp or os).listdir(dir)

  def isdir(d):
    return (sftp or os.path).isdir(d)

  if emby:
    files = ccache.get('emby', [])
    if not files:
      files = [basename(x.path)+'/' for x in emby.series_sync]
      ccache['emby'] = files

  if not files:
    files = ccache[typ].get(dir, [])


  if not files:
    files = [join(dir, f) if dir!='.' else f for f in lsdir(dir)]
    files = [f+sep if isdir(f) else f for f in files]
    ccache[typ][dir] = files

  files = [f for f in files if f.startswith(text)]

  return files if state == -1 else files[state]

local_completion = lambda text, state: file_completion(None, None, text, state)

# emby helper functions
def emby_connect(config):
  embycfg = config.find('.//emby')
  if embypy and embycfg is not None:
    conn = embypy.Emby(**embycfg.attrib)
    embycfg.set('token',  conn.connector.token or conn.connector.api_key)
    embycfg.set('userid', conn.connector.userid)
    return conn
  return None

def get_emby_obj(path, conn=None):
  if conn is None:
    return None
  for obj in conn.series_sync:
    op = obj.path
    if op.rstrip('\\/')+'/' in path.rstrip('\\/')+'/':
      return obj
  for obj in conn.series_sync + conn.movies_sync:
    op = obj.path
    if op in path or path.lower() in op.lower():
      return obj
  return None

def update_emby_info(conn, showpath, ranges):
  logger.debug('updating emby watch status for \"%s\", with %s',
    showpath, str(ranges),
  )
  if conn is None:
    logger.info('  Not connected to emby, skipping update')
    return
  item = get_emby_obj(showpath, conn)
  if item:
    logger.debug('  found item %s (%s)', item.name, item.id)
  else:
    logger.debug('  could not find item')
    return
  try:
    for season in item.seasons_sync:
      eps = ranges.get(season.index_number, set())
      for ep in season.episodes_sync:
        logger.debug('  %02dx%02d - %s',
          ep.season_number, ep.index_number,
          'already watched' if ep.watched else (
            'will download'
               if ep.index_number not in eps else
            'downloaded, setting watched'
          )
        )
        if ep.index_number in eps and not ep.watched:
          ep.setWatched_sync()
          ep.update_sync()
  except:
    try:
      item.setWatched_sync()
      item.update_sync()
    except:
      return

def emby_search(conn, search):
  logger.debug('emby-search (path):')
  if not conn:
    logger.debug('  No conn, return None')
    return None
  for series in conn.series_sync:
    if basename(series.path) == search.rstrip('/\\'):
      logger.debug('  Found series: %s', series.name)
      return series.path
  logger.debug('  Nothing matches')
  return None

# connect to sfpt
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

# config file helper functions
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

  emby = auth.find('./emby')
  if emby is None:
    emby = etree.SubElement(auth, 'emby')
    url = input('\nPlease enter emby url [opt]: ')
    if url:
      if not url.startswith('http'):
        url = 'http://' + url
      emby.set('url', url)
      emby.set('username', input('Please enter emby username:  '))
      emby.set('password', input('Please enter emby password:  '))

  emby = emby_connect(auth)

  readline.set_completer(local_completion)
  dirname = os.path.realpath(input('\nPlease enter local [save] dir: '))
  readline.set_completer(None)

  loc = conn.find(f'./group[@location="{dirname}"]')
  if loc is None:
    loc = etree.SubElement(conn, 'group')
    loc.set('location', dirname)

  with get_connection(config) as sftp:
    comp = lambda text, state: file_completion(sftp, emby, text, state)
    readline.set_completer(comp)
    rpath = input('Please enter remote show dir [empty to end]: ')
    readline.set_completer(None)

    while rpath:
      rpath = sftp.normalize(emby_search(emby, rpath) or rpath)
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

# ep range helpers
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

# main config functions
#   read config
def process_config(config):
  for connection in config.findall('./connection'):
    process_connection(connection)
    save(config)

#   per server
def process_connection(config):
  conn = emby_connect(config)
  update_emby_info(conn, "/mnt/media/TV/Steins_Gate_0", {1: {1, 2, 3, 4, 5, 6, 7, 8, 9, 10}})
  with get_connection(config) as sftp:
    total = 0
    todo  = {}
    for group in config.findall('./group'):
      save_location = group.get('location', './')
      todo[save_location] = {}
      for show in group.findall('./show'):
        path,paths,rngs = process_show_config(show, save_location, sftp)
        if len(paths):
          total += len(paths)
          todo[save_location][show] = {
              'showpath':path,
              'ranges':rngs,
              'paths':paths,
          }
    download_dict(todo, total, conn, sftp)

#   do all the downloading
def download_dict(todo, total, conn, sftp):
  logger.debug('\n\nDownload dict. Total: %d', total)
  index = 0
  for save_location in todo:
    for config in todo[save_location]:
      show   = todo[save_location][config]
      ranges = show['ranges']
      paths  = show['paths']
      for path in paths:
        index += 1
        download_file(save_location, sftp, path, index, total or len(paths))
        if config is not None:
          update_range(config, ranges)
        update_emby_info(conn, show['showpath'], ranges)
      if not paths:
        update_emby_info(conn, show['showpath'], ranges)

#   get show dir
def process_show_config(config, save_location, sftp, ir=False):
  ranges   = xml_range_to_dict(config)
  showpath = config.findtext('.//remotepath')
  p,r = process_show(config, showpath, save_location, sftp, ranges, ir)
  return showpath, p, r

#   search eps in the show
def process_show(config, showpath, save_location, sftp, ranges={}, ir=False):
  chk = lambda path: download_file_check(ranges, save_location, sftp, path, ir)
  igr = lambda x: None

  paths = []

  def pfile(path):
    if chk(path):
      paths.append(path)

  logger.debug('\n%s\n%s', showpath, str(ranges))
  sftp.walktree(showpath, pfile, igr, igr)

  return paths, ranges

# irregular version
def process_item(config, item_name):
  conn = emby_connect(config)
  search = f'.//group/show/remotepath[text()="{item_name}"]/../../@location'
  sloc = config.xpath(search) or config.xpath('.//group/@location') or ['./']
  sloc = sloc[0]
  with get_connection(config) as sftp:
    if not sftp.exists(item_name):
      if conn:
        return get_search(config, sloc, item_name, sftp, conn)
      else:
        return None
    elif sftp.isdir(item_name):
      return get_dir(config, sloc, item_name, sftp, conn)
    elif sftp.isfile(item_name):
      return get_file(config, sloc, item_name, sftp, conn)

def get_search(config, save_location, path, sftp, conn):
  path = emby_search(conn, path)
  search = f'.//group/show/remotepath[text()="{path}"]/../../@location'
  save_location = (config.xpath(search) or [save_location])[0]
  if sftp.isdir(path):
    get_dir(config, save_location, path, sftp, conn)
  else:
    get_file(config, save_location, path, sftp, conn)

def get_dir(config, save_location, path, sftp, conn):
  search = './/group/show/remotepath[contains(text(),"{path}")' + \
           ' or contains("{path}",text())]/..'
  showcfg = config.xpath(search)
  if showcfg:
    showcfg = showcfg[0]
    path = showcfg.findtext('./remotepath')
    save_location = showcfg.getparent().get('location')
    _,p,r = process_show_config(showcfg, save_location, sftp, ir=True)
  else:
    if conn:
      for show in conn.series_sync:
        if basename(show.path) in (path, path.strip('/\\')):
          path = show.path
          break
    p,r = process_show(None, path, save_location, sftp)
  download_dict({
    save_location: {
      (showcfg or None): {
        'showpath':path,
        'ranges':r,
        'paths':p,
      }
    }
  }, 0, conn, sftp)
  save(config)

def get_file(config, save_location, path, sftp, conn, index=0, total=0):
  if not sftp.exists(path):
    return
  if path.lower().rpartition('.')[2] in formats:
    download_file(save_location, sftp, path, index, total)
    update_emby_info(conn, path, ranges)
  else:
    with sftp.open(path) as f:
      lines = f.readlines()
      tot   = len(list(lines))
      for i,line in enumerate(lines, 1):
        get_file(config, save_location, line.strip(), sftp, conn, i, tot)

def download_file_check(ranges, save_location, sftp, path, ir=False):
  if path.rpartition('.')[2].lower() not in formats:
    logger.debug('  (skip) Bad format for: \"%s\"', path)
    return False

  info = ep_pat.search(path)
  if info:
    season, episode = int(info.group(1)), int(info.group(2))
  else:
    logger.warn('could not parse ep info of "%s"', path)
    return False

  name  = os.path.basename(path)
  lpath = os.path.join(save_location, name)

  local_size  = os.stat(lpath).st_size if os.path.exists(lpath) else 0
  remote_size = sftp.lstat(path).st_size
  if local_size == remote_size:
    # file already fully downloaded, skip
    logger.info('  (skip) File downloaded at: \"%s\"', lpath)
    ranges[season] = ranges.get(season, set()).union({episode})
    return False

  logger.info('  %s   -   not info: %5s,     ir: %5s,     not in range: %5s',
          f'{season:02}x{episode:02}' if info else '--x--',
          'False' if info else 'True',
          str(ir),
          str(episode not in ranges.get(season, set())),
  )
  if not info or ir or episode not in ranges.get(season, set()):
    if info:
      # update ep range
      ranges[season] = ranges.get(season, set()).union({episode})
    return True
  return False

def download_file(save_location, sftp, path, index=0, total=0):
  name  = os.path.basename(path)
  lpath = os.path.join(save_location, name)

  local_size  = os.stat(lpath).st_size if os.path.exists(lpath) else 0
  remote_size = sftp.lstat(path).st_size

  if index and total:
    ilen = len(str(total))
    name = f'({index:0{ilen}}/{total}) {name}'

  last_times = 0
  last_trans = 0
  num_calls  = 1
  last_tran  = 0
  last_time  = start_time = time.time()
  def callback(cur, tot):
    width = shutil.get_terminal_size((80, 20)).columns - 25 # max width
    nlen  = width//2                         # lenght for name information
    plen  = nlen + (1 if width%2 else 0) - 2 # length for progress bar
    dname = name                             # display name
    blen  = plen*cur//tot                    # progress bar lenght
    pcomp = 100*cur/tot                      # percent completion

    nonlocal last_times
    nonlocal last_trans
    nonlocal num_calls
    nonlocal last_tran
    nonlocal last_time

    cur_time = time.time()
    last_times = (last_times*(num_calls-1) + cur_time - last_time)/num_calls
    last_trans = (last_trans*(num_calls-1) + cur      - last_tran)/num_calls

    num_calls += 1
    last_time  = cur_time # remember current info
    last_tran  = cur      # remember current info

    if cur == tot:
      tl = int(cur_time - start_time)
    else:
      speed = last_trans/last_times # bytes/s
      tl    = int((tot-cur)/speed)     # time left (s)
    tl = f'{((tl//3600)%60):02}:{((tl//60)%60):02}:{(tl%60):02}' # size 8

    # cut name if needed
    if len(dname) > nlen:
      tmp_len = (nlen - 1)//2
      dname = dname[:tmp_len]+'~'+dname[-tmp_len:]

    if cur == -1:
      bar = 'skipping, exists'[:plen]
      pad = ' '*((plen-len(bar))//2)
      bar = pad + bar + pad + (' ' if plen%2 else '')
    else:
      bar = f'{"="*blen}{" "*(plen-blen)}'

    out = f'\r{dname:{nlen}} [{bar}] ({pcomp:6.2f}% - {tl})  '

    if cur == tot:
      print(out)
    else:
      print(out[:-2], end='\r', flush=True)

  if local_size == remote_size:
    # file already fully downloaded, skip
    callable(-1, -1)
    return

  sftp.get(path,
    localpath=lpath,
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
        conn = emby_connect(config)
        print('\n'.join(
              file_completion(sftp, conn, ' '.join(sys.argv[i+1:]), -1)
        ))
      break
    else:
      process_item(config, arg)
      break
  else:
    process_config(config)
  save(config)
