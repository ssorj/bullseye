#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
#

import collections as _collections
import fnmatch as _fnmatch
import importlib as _importlib
import os as _os
import shutil as _shutil
import sys as _sys

from plano import *

class _Project:
    def __init__(self):
        self.name = None
        self.source_dir = "python"
        self.source_exclude = [".gitignore", "/bullseye"]
        self.data_dirs = []
        self.build_dir = "build"
        self.test_modules = []

project = _Project()

_default_prefix = join(get_home_dir(), ".local")

def check_project():
    assert project.name
    assert project.source_dir
    assert project.build_dir

class project_env(working_env):
    def __init__(self):
        check_project()

        home_var = "{0}_HOME".format(project.name.upper().replace("-", "_"))

        env = {
            home_var: get_absolute_path(join(project.build_dir, project.name)),
            "PATH": get_absolute_path(join(project.build_dir, "bin")) + ":" + ENV["PATH"],
            "PYTHONPATH": get_absolute_path(join(project.build_dir, project.name, project.source_dir)),
        }

        super(project_env, self).__init__(**env)

def configure_file(input_file, output_file, substitutions, quiet=False):
    notice("Configuring '{0}' for output '{1}'", input_file, output_file)

    content = read(input_file)

    for name, value in substitutions.items():
        content = content.replace("@{0}@".format(name), value)

    write(output_file, content)

    _shutil.copymode(input_file, output_file)

    return output_file

_prefix_arg = CommandArgument("prefix", help="The base path for installed files", default=_default_prefix)
_verbose_arg = CommandArgument("verbose", help="Print detailed logging to the console")

@command(args=(_prefix_arg, _verbose_arg))
def build(prefix=None, verbose=False):
    check_project()

    build_file = join(project.build_dir, "build.json")
    build_data = {}

    if exists(build_file):
        build_data = read_json(build_file)

    mtime = _os.stat(project.source_dir).st_mtime

    for path in find(project.source_dir):
        mtime = max(mtime, _os.stat(path).st_mtime)

    if prefix is None:
        prefix = build_data.get("prefix", _default_prefix)

    new_build_data = {"prefix": prefix, "mtime": mtime}

    debug("Existing build data: {0}", pformat(build_data))
    debug("New build data:      {0}", pformat(new_build_data))

    if build_data == new_build_data:
        debug("Already built")
        return

    write_json(build_file, new_build_data)

    default_home = join(prefix, "lib", project.name)

    for path in find("bin", "*.in"):
        configure_file(path, join(project.build_dir, path[:-3]), {"default_home": default_home})

    for path in find("bin", exclude="*.in"):
        copy(path, join(project.build_dir, path), inside=False, symlinks=False)

    excluded_dirs = [x[1:] for x in project.source_exclude if x.startswith("/")]
    excluded_files = [x for x in project.source_exclude if not x.startswith("/")]
    top_level_names = list_dir(project.source_dir, exclude=excluded_dirs)

    for name in top_level_names:
        path = join(project.source_dir, name)

        if is_file(path) and not any([_fnmatch.fnmatchcase(name, x) for x in excluded_files]):
            copy(path, join(project.build_dir, project.name, path), inside=False, symlinks=False)

    for name in top_level_names:
        path = join(project.source_dir, name)

        if is_dir(path):
            for subpath in find(path, exclude=excluded_files):
                copy(subpath, join(project.build_dir, project.name, subpath), inside=False, symlinks=False)

    for name in project.data_dirs:
        for path in find(name):
            copy(path, join(project.build_dir, project.name, path), inside=False, symlinks=False)

@command(args=(CommandArgument("include", help="Run tests with names matching PATTERN", metavar="PATTERN"),
               CommandArgument("exclude", help="Do not run tests with names matching PATTERN", metavar="PATTERN"),
               CommandArgument("unskip", help="Run skipped tests matching PATTERN", metavar="PATTERN"),
               CommandArgument("list_", help="Print the test names and exit", display_name="list"),
               _verbose_arg))
def test_(include="*", exclude=None, unskip=None, list_=False, verbose=False):
    check_project()

    if not list_:
        build()

    with project_env():
        modules = [_importlib.import_module(x) for x in project.test_modules]

        if not modules: # pragma: nocover
            notice("Test modules not found: {}".format(",".join(project.test_modules)))
            return

        args = list()

        if list_:
            print_tests(modules)
            return

        exclude = nvl(exclude, ())
        unskip = nvl(unskip, ())

        run_tests(modules, include=include, exclude=exclude, unskip=unskip, verbose=verbose)

@command
def coverage():
    """
    Analyze test coverage
    """

    check_project()
    check_program("coverage", "Install the Python coverage package")

    run(f"coverage run --include {project.source_dir}/\* {which('plano')} test", stash=True)
    run("coverage report")
    run("coverage html")

    print("OUTPUT:", get_file_url("htmlcov/index.html"))

@command(args=(CommandArgument("staging_dir", help="A path prepended to installed files"), _prefix_arg, _verbose_arg))
def install(staging_dir="", prefix=None, verbose=False):
    check_project()

    build(prefix=prefix, verbose=verbose)

    assert is_dir(project.build_dir), list_dir()

    build_file = join(project.build_dir, "build.json")
    build_data = read_json(build_file)
    build_prefix = project.build_dir + "/"
    install_prefix = staging_dir + build_data["prefix"]

    # XXX Windows trouble
    # > plano-self-test: notice: Copying 'build\\bin\\chucker' to 'stagingC:\\Users\\runneradmin\\.local\\build\\bin\\chucker'

    for path in find(join(project.build_dir, "bin")):
        copy(path, join(install_prefix, remove_prefix(path, build_prefix)), inside=False, symlinks=False)

    for path in find(join(project.build_dir, project.name)):
        copy(path, join(install_prefix, "lib", remove_prefix(path, build_prefix)), inside=False, symlinks=False)

@command
def clean():
    check_project()

    remove(project.build_dir)
    remove(find(".", "__pycache__"))

@command(args=(CommandArgument("undo", help="Generate settings that restore the previous environment"),))
def env(undo=False):
    """
    Generate shell settings for the project environment

    To apply the settings, source the output from your shell:

        $ source <(plano env)
    """

    check_project()

    project_dir = get_current_dir() # XXX Needs some checking
    home_var = "{0}_HOME".format(project.name.upper().replace("-", "_"))
    old_home_var = "OLD_{0}".format(home_var)
    home_dir = join(project_dir, project.build_dir, project.name)

    if undo:
        print("[[ ${0} ]] && export {1}=${2} && unset {3}".format(old_home_var, home_var, old_home_var, old_home_var))
        print("[[ $OLD_PATH ]] && export PATH=$OLD_PATH && unset OLD_PATH")
        print("[[ $OLD_PYTHONPATH ]] && export PYTHONPATH=$OLD_PYTHONPATH && unset OLD_PYTHONPATH")

        return

    print("[[ ${0} ]] && export {1}=${2}".format(home_var, old_home_var, home_var))
    print("[[ $PATH ]] && export OLD_PATH=$PATH")
    print("[[ $PYTHONPATH ]] && export OLD_PYTHONPATH=$PYTHONPATH")

    print("export {0}={1}".format(home_var, home_dir))

    path = [
        join(project_dir, project.build_dir, "bin"),
        ENV.get("PATH", ""),
    ]

    print("export PATH={0}".format(join_path_var(*path)))

    python_path = [
        join(home_dir, project.source_dir),
        join(project_dir, project.source_dir),
        ENV.get("PYTHONPATH", ""),
    ]

    print("export PYTHONPATH={0}".format(join_path_var(*python_path)))
