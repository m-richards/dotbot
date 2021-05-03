import os
import dotbot
from ..util.common import expand_path, on_permitted_os
from typing import Union


class Create(dotbot.Plugin):
    '''
    Create empty paths.
    '''

    _directive = 'create'

    def can_handle(self, directive):
        return directive == self._directive

    def handle(self, directive, data):
        if directive != self._directive:
            raise ValueError('Create cannot handle directive %s' % directive)
        return self._process_paths(data)

    def _process_paths(self, paths:Union[dict, list]):
        """Paths can be a list or a dict depending on yaml format.
        Tread list format as soft deprecated and use original logic without os-constraint.
        """
        if isinstance(paths, list):
            self._log.warning("Create from list syntax is soft deprecated, should use dict "
            "syntax with keys & null values instead for up to date behaviour.")
            # basically logic is confusing, don't need to have two ways to do the same thing,
        success = True
        defaults = self._context.defaults().get('create', {})
        for key in paths:  # keys or indexes in list
            if isinstance(key, dict):
                raise TypeError("Create Mode options not supported unless dict based constructor "
                    "is used (same as default dotbot).\nSwap to yaml dict syntax (with ':' line "
                    "ends and no '-' prefix).")
            path_expanded = expand_path(key)
            mode = defaults.get('mode', 0o777)  # same as the default for os.makedirs
            os_constraint = defaults.get('os-constraint', None)
            if isinstance(paths, dict):
                options = paths[key]
                if options is not None:
                    mode = options.get('mode', mode)
                    os_constraint = options.get('os-constraint', os_constraint)
                    if on_permitted_os(os_constraint) is False:
                        self._log.lowinfo(f"Path skipped {path_expanded} ({os_constraint} "
                                          f"only)")
                        continue  # skip illegal os
            success &= self._create(path_expanded, mode)
        if success:
            self._log.info('All paths have been set up')
        else:
            self._log.error('Some paths were not successfully set up')
        return success

    def _exists(self, path):
        '''
        Returns true if the path exists.
        '''
        path = os.path.expanduser(path)
        return os.path.exists(path)

    def _create(self, path, mode):
        success = True
        if not self._exists(path):
            self._log.debug('Trying to create path %s with mode %o' % (path, mode))
            try:
                self._log.lowinfo('Creating path %s' % path)
                os.makedirs(path, mode)
            except OSError as e:
                self._log.warning(f'Failed to create path {path} ({e})')
                success = False
        else:
            self._log.lowinfo('Path exists %s' % path)
        return success
