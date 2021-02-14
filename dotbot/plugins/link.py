import os
import glob
import shutil
import dotbot
import dotbot.util
import subprocess


class Link(dotbot.Plugin):
    """
    Symbolically links dotfiles.
    """

    _directive = "link"

    def can_handle(self, directive):
        return directive == self._directive

    def handle(self, directive, data):
        if directive != self._directive:
            raise ValueError("Link cannot handle directive %s" % directive)
        return self._process_links(data)

    def _get_default_flags(self):
        """Get flags for process links from default file."""
        defaults = self._context.defaults().get("link", {})
        relative = defaults.get("relative", False)
        canonical_path = defaults.get("canonicalize-path", True)
        force = defaults.get("force", False)
        relink = defaults.get("relink", False)
        create = defaults.get("create", False)
        use_glob = defaults.get("glob", False)
        test = defaults.get("if", None)
        ignore_missing = defaults.get("ignore-missing", False)
        return relative, canonical_path, force, relink, create, use_glob, test, ignore_missing



    def _process_links(self, links_dict):
        # print("symlinking\n\t", links)
        success = True
        (relative, canonical_path, force_flag, relink_flag,
            create_dir_flag, use_glob, shell_command, ignore_missing) = self._get_default_flags()
        for destination, source_dict in links_dict.items():
            destination = os.path.normpath(os.path.expandvars(destination))
            if isinstance(source_dict, dict):
                # If source dict supplies flags, override the generic ones
                shell_command = source_dict.get("if", shell_command)
                relative = source_dict.get("relative", relative)
                canonical_path = source_dict.get("canonicalize-path", canonical_path)
                force_flag = source_dict.get("force", force_flag)
                relink_flag = source_dict.get("relink", relink_flag)
                create_dir_flag = source_dict.get("create", create_dir_flag)
                use_glob = source_dict.get("glob", use_glob)
                ignore_missing = source_dict.get("ignore-missing", ignore_missing)

                path = self._default_source(destination, source_dict.get("path"))
            else:
                # source dict is a scalar
                path = self._default_source(destination, source_dict)
            if shell_command is not None and not self._test_success(shell_command):
                self._log.lowinfo("Skipping %s" % destination)
                continue
            path = os.path.normpath(os.path.expandvars(os.path.expanduser(path)))
            if use_glob:
                self._log.debug("Globbing with path: " + str(path))
                glob_results = glob.glob(path)
                if len(glob_results) == 0:
                    self._log.warning("Globbing couldn't find anything matching " + str(path))
                    success = False
                    continue
                glob_star_loc = path.find("*")
                if glob_star_loc == -1 and destination[-1] == "/":
                    self._log.error("Ambiguous action requested.")
                    self._log.error(
                        "No wildcard in glob, directory use undefined: "
                        + destination
                        + " -> "
                        + str(glob_results)
                    )
                    self._log.warning("Did you want to link the directory or into it?")
                    success = False
                    continue
                elif glob_star_loc == -1 and len(glob_results) == 1:
                    # perform a normal link operation
                    if create_dir_flag:
                        success &= self._create_dir(destination)
                    if force_flag or relink_flag:
                        success &= self._delete(path, destination, relative, canonical_path, force_flag)
                    success &= self._link(
                        path, destination, relative, canonical_path, ignore_missing
                    )
                else:
                    self._log.lowinfo("Globs from '" + path + "': " + str(glob_results))
                    glob_base = path[:glob_star_loc]
                    for glob_full_item in glob_results:
                        glob_item = glob_full_item[len(glob_base) :]
                        glob_link_destination = os.path.join(destination, glob_item)
                        if create_dir_flag:
                            success &= self._create_dir(glob_link_destination)
                        if force_flag or relink_flag:
                            success &= self._delete(
                                glob_full_item,
                                glob_link_destination,
                                relative,
                                canonical_path,
                                force_flag,
                            )
                        success &= self._link(
                            glob_full_item,
                            glob_link_destination,
                            relative,
                            canonical_path,
                            ignore_missing,
                        )
            else:  # not using glob:
                if create_dir_flag:
                    success &= self._create_dir(destination)
                if ignore_missing is False and self._exists(
                    os.path.join(self._context.base_directory(), path)
                ) is False:
                    # we seemingly check this twice (here and in _link) because
                    # if the file doesn't exist and force is True, we don't
                    # want to remove the original (this is tested by
                    # link-force-leaves-when-nonexistent.bash)
                    success = False
                    self._log.warning("Nonexistent source %s -> %s" % (destination, path))
                    continue
                if force_flag or relink_flag:
                    success &= self._delete(path, destination, relative, canonical_path, force_flag)
                success &= self._link(path, destination, relative, canonical_path, ignore_missing)
        if success:
            self._log.info("All links have been set up")
        else:
            self._log.error("Some links were not successfully set up")
        return success

    def _test_success(self, command):
        ret = dotbot.util.shell_command(command, cwd=self._context.base_directory())
        if ret != 0:
            self._log.debug("Test '%s' returned false" % command)
        return ret == 0

    def _default_source(self, destination, source):
        if source is None:
            basename = os.path.basename(destination)
            if basename.startswith("."):
                return basename[1:]
            else:
                return basename
        else:
            return source

    def _is_link(self, path):
        """
        Returns true if the path is a symbolic link.
        """
        return os.path.islink(os.path.expanduser(path))

    def _get_link_destination(self, path):
        """
        Returns the destination of the symbolic link. Truncates the  \\?\ start to a path if it
        is present. This is an identifier which allows >255 character file name links to work.
        Since this function is for the point of comparison, it is okay to truncate
        """
        # path = os.path.normpath(path)
        path = os.path.expanduser(path)
        try:
            read_link = os.readlink(path)
            # Read link can return paths starting with \\?\ - this allows over the 255 file name
            # limit
        except OSError as e:
            if "[WinError 4390] The file or directory is not a reparse point" in str(
                e
            ) and os.path.isdir(path):
                return "UNLINKED_DIR"
            else:
                raise e

        if read_link.startswith("\\\\?\\"):
            read_link = read_link.replace("\\\\?\\", "")
        return read_link

    def _exists(self, path):
        """
        Returns true if the path exists.
        """
        path = os.path.expanduser(path)
        return os.path.exists(path)

    def _create_dir(self, path):
        """Create all directories in path if they do not already exist."""
        success = True
        parent = os.path.abspath(os.path.join(os.path.expanduser(path), os.pardir))
        if not self._exists(parent):
            self._log.debug("Try to create parent: " + str(parent))
            try:
                os.makedirs(parent)
            except OSError:
                self._log.warning("Failed to create directory %s" % parent)
                success = False
            else:
                self._log.lowinfo("Creating directory %s" % parent)
        return success

    def _delete(self, source, path, relative, canonical_path, force):
        success = True
        source = os.path.join(self._context.base_directory(canonical_path=canonical_path), source)
        fullpath = os.path.expanduser(path)
        if relative:
            source = self._relative_path(source, fullpath)
        if (self._is_link(path) and self._get_link_destination(path) != source) or (
            self._exists(path) and not self._is_link(path)
        ):
            removed = False
            try:
                if os.path.islink(fullpath):
                    os.unlink(fullpath)
                    removed = True
                elif force:
                    if os.path.isdir(fullpath):
                        shutil.rmtree(fullpath)
                        removed = True
                    else:
                        os.remove(fullpath)
                        removed = True
            except OSError:
                self._log.warning("Failed to remove %s" % path)
                success = False
            else:
                if removed:
                    self._log.lowinfo("Removing %s" % path)
        return success

    def _relative_path(self, source, destination):
        """
        Returns the relative path to get to the source file from the
        destination file.
        """
        destination_dir = os.path.dirname(destination)
        return os.path.relpath(source, destination_dir)

    def _link(
        self, dotfile_source, target_path_to_link_at, relative_path, canonical_path, ignore_missing
    ):
        """
        Links link_name to source.
        :param target_path_to_link_at is the file path where we are putting a symlink back to
        dotfile_source

        Returns true if successfully linked files.
        """
        success_flag = False




        target_path_to_link_at = os.path.normpath(target_path_to_link_at)

        destination = os.path.normpath(os.path.expanduser(target_path_to_link_at))
        base_directory = self._context.base_directory(canonical_path=canonical_path)
        absolute_source = os.path.normpath(os.path.join(base_directory, dotfile_source))
        # get the file/ folder the symlink (located at the target path) is pointed to
        symlink_dest_at_target_path: str = self._get_link_destination(target_path_to_link_at)

        target_path_exists: bool = self._exists(target_path_to_link_at)

        target_file_is_link: bool = self._is_link(target_path_to_link_at)

        if relative_path:
            dotfile_source = self._relative_path(absolute_source, destination)
        else:
            dotfile_source = absolute_source

        symlink_targets_incorrect_source = symlink_dest_at_target_path != dotfile_source

        # if source does not exist we fail (unless we allow missing
        if self._exists(absolute_source) is False and ignore_missing is False:
            if target_file_is_link:
                self._log.warning(
                    "Nonexistent source %s -> %s" % (target_path_to_link_at, dotfile_source)
                )
            else:
                self._log.warning(
                    "Nonexistent source for %s : %s" % (target_path_to_link_at, dotfile_source)
                )
            return success_flag

        # Either the target path exists (with a symlink (correct or incorrect) or with a
        #   file/folder)
        if target_path_exists is False:
            if target_file_is_link and symlink_targets_incorrect_source:
                self._log.warning(
                    "STRANGE CASE: Invalid link %s -> %s" % (target_path_to_link_at,
                                                 symlink_dest_at_target_path)
                )
                # TODO I can't see how the path can not exist but the link at the path can exist?

            #  If the dotfile dir source exists, or we don't care if it's missing we try to symlink
            # i.e. this should almost always be true if the target_path doesn't exist
            else:
                try:
                    os.symlink(dotfile_source, destination)
                except OSError:
                    self._log.warning(
                        "Linking failed %s -> %s" % (target_path_to_link_at, dotfile_source)
                    )
                except Exception as e:
                    print(
                        f"SYMLINK FAILED with arguments os.symlink({dotfile_source}, {destination})",
                    )
                    raise e
                else:  # code attached to the try success block, but without hiding exceptions
                    self._log.lowinfo(
                        "Creating link %s -> %s" % (target_path_to_link_at, dotfile_source)
                    )
                    success_flag = True

        else:  # target path already exists
            # If the target is a link, check it's the right link
            if target_file_is_link:
                if symlink_targets_incorrect_source:
                    self._log.warning(
                        "Incorrect link %s -> %s" % (
                        target_path_to_link_at, symlink_dest_at_target_path)
                    )
                else:
                    # symlink already exists and is correct
                    self._log.lowinfo(
                        "Link already exists %s -> %s" % (target_path_to_link_at, dotfile_source))
                    success_flag = True
            else:
                self._log.warning(
                    "%s already exists but is a regular file or directory" % target_path_to_link_at
                )
                
        return success_flag
