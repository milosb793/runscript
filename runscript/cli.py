import os
from argparse import ArgumentParser
import logging
import sys 
import imp
from ConfigParser import RawConfigParser, NoOptionError

from runscript.lock import assert_lock
#from runscript.config import load_config
#from grab.util.py3k_support import *

logger = logging.getLogger('runscript.cli')
PY3K = False

def activate_env(env_path):
    activate_script = os.path.join(env_path, 'bin/activate_this.py')
    # py3 hack
    if PY3K:
        exec(compile(open(activate_script).read(), activate_script, 'exec'),
             dict(__file__=activate_script))
    else:
        execfile(activate_script, dict(__file__=activate_script))


def setup_logging(action, level, clear_handlers=False):
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    if clear_handlers:
        for hdl in root.handlers:
            root.removeHandler(hdl)

    hdl = logging.StreamHandler()
    hdl.setLevel(level)
    root.addHandler(hdl)


def process_env_option():
    parser = ArgumentParser()
    parser.add_argument('--env')
    args, trash = parser.parse_known_args()
    if args.env:
        activate_env(args.env)


def module_is_importable(path):
    mod_names = path.split('.')
    mod = None
    for mod_name in mod_names:
        if mod is None:
            path = None
        else:
            path = mod.__path__
        try:
            mod_file, mod_path, mod_info = imp.find_module(mod_name, path)
        except ImportError:
            return False
        else:
            mod = imp.load_module(mod_name, mod_file, mod_path, mod_info)
    return True


def normalize_config_value(section, name, value):
    if section == 'global' and name == 'search_path':
        return [x.strip() for x in value.split(',')]
    else:
        return value


def load_config():
    cur_dir = os.getcwd()
    config_path = os.path.join(cur_dir, 'run.ini')

    config = {
        'global': {
            'search_path': ['grab.script', 'script'],
        },
    }

    if os.path.exists(config_path):
        parser = RawConfigParser()
        parser.read(config_path)
        for section in parser.sections():
            if not section in config:
                config[section] = {}
            for key, val in parser.items(section):
                config[section][key] = normalize_config_value(section, key, val)

    return config
    

def process_command_line():
    # Add current directory to python path
    cur_dir = os.path.realpath(os.getcwd())
    sys.path.insert(0, cur_dir)

    process_env_option()

    parser = ArgumentParser()
    parser.add_argument('action', type=str)
    parser.add_argument('--logging-level', default='debug')
    parser.add_argument('--lock-key')
    #parser.add_argument('--ignore-lock', action='store_true', default=False)
    parser.add_argument('--env', type=str)
    parser.add_argument('--profile', action='store_true', default=False)

    args, trash = parser.parse_known_args()

    config = load_config()
    logging_level = getattr(logging, args.logging_level.upper())
    setup_logging(args.action, logging_level, clear_handlers=True)

    if config['global'].get('django_settings_module'):
        os.environ['DJANGO_SETTINGS_MODULE'] = config['global']['django_settings_module']
        # Disable django DEBUG feature to prevent memory leaks
        from django.conf import settings
        settings.DEBUG = False

    if config['global'].get('django_setup') == 'yes':
        import django
        django.setup()

    # Setup action handler
    action_name = args.action
    action_mod = None

    for path in config['global']['search_path']:
        imp_path = '%s.%s' % (path, action_name)
        if module_is_importable(imp_path):
            action_mod = __import__(imp_path, None, None, ['foo'])

    if action_mod is None:
        sys.stderr.write('Could not find the package to import %s module\n' % action_name)
        sys.exit(1)

    if hasattr(action_mod, 'setup_arg_parser'):
        action_mod.setup_arg_parser(parser)
    args_obj, trash = parser.parse_known_args()

    args = vars(args_obj)

    for key, val in config.get('script:%s' % action_name, {}).items():
        args[key] = val

    if hasattr(action_mod, 'get_lock_key'):
        lock_key = action_mod.get_lock_key(**args)
    else:
        lock_key = args['lock_key']

    if lock_key is not None:
        lock_path = 'var/run/%s.lock' % lock_key
        print 'Trying to lock file: %s' % lock_path
        assert_lock(lock_path)

    #logger.debug('Executing %s action' % action_name)
    try:
        if args['profile']:
            import cProfile
            import pyprof2calltree
            import pstats

            profile_file = 'var/%s.prof' % action_name
            profile_tree_file = 'var/%s.prof.out' % action_name

            prof = cProfile.Profile()
            prof.runctx('action_mod.main(**args)',
                        globals(), locals())
            stats = pstats.Stats(prof)
            stats.strip_dirs()
            pyprof2calltree.convert(stats, profile_tree_file)
        else:
            action_mod.main(**args)
    except Exception as ex:
        logging.error('Unexpected exception from action handler:', exc_info=ex)
