#!/usr/bin/python
# This Python file uses the following encoding: utf-8

# Recipe Robot
# Copyright 2015-2019 Elliot Jordan, Shea G. Craig, and Eldon Ahrold
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""
tools.py

This module of Recipe Robot contains various helper and tool functions that
support the main `recipe-robot` script and the `recipe_generator.py` module.
"""


import os
import re
import shlex
import sys
import timeit
from datetime import datetime
from functools import wraps
from random import choice as random_choice
from subprocess import PIPE, Popen
from urllib import quote_plus
import textwrap

# pylint: disable=no-name-in-module
from Foundation import NSUserDefaults

# pylint: enable=no-name-in-module

from .exceptions import RoboError


# TODO(Elliot): Can we use the one at /Library/AutoPkg/FoundationPlist instead?
# Or not use it at all (i.e. use the preferences system correctly). (#16)
try:
    from recipe_robot_lib import FoundationPlist
except ImportError:
    robo_print("Importing plistlib as FoundationPlist", LogLevel.WARNING)
    import plistlib as FoundationPlist


__version__ = "1.1.3"
ENDC = "\033[0m"
PREFS_FILE = os.path.expanduser(
    "~/Library/Preferences/com.elliotjordan.recipe-robot.plist"
)

# Build the list of download formats we know about.
SUPPORTED_IMAGE_FORMATS = ("dmg", "iso")  # downloading iso unlikely
SUPPORTED_ARCHIVE_FORMATS = ("zip", "tar.gz", "gzip", "tar.bz2", "tbz", "tgz")
SUPPORTED_INSTALL_FORMATS = ("pkg",)
ALL_SUPPORTED_FORMATS = (
    SUPPORTED_IMAGE_FORMATS + SUPPORTED_ARCHIVE_FORMATS + SUPPORTED_INSTALL_FORMATS
)

# Global variables.
CACHE_DIR = os.path.join(
    os.path.expanduser("~/Library/Caches/Recipe Robot"),
    datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f"),
)
color_setting = False


class LogLevel(object):
    """Specify colors that are used in Terminal output."""

    DEBUG = ("\033[95m", "DEBUG")
    ERROR = ("\033[1;38;5;196m", "ERROR")
    LOG = ("", "")
    REMINDER = ("\033[1;38;5;33m", "REMINDER")
    VERBOSE = ("\033[0m", "")
    WARNING = ("\033[1;38;5;208m", "WARNING")


class OutputMode(object):
    """Manage global output mode state with a singleton."""

    # Use --verbose command-line argument, or hard-code
    # to "True" here for additional user-facing output.
    verbose_mode = False

    # Use --debug command-line argument, or hard-code
    # to "True" here for additional development output.
    debug_mode = False

    @classmethod
    def set_verbose_mode(cls, value):
        """Set the class variable for verbose_mode."""
        if isinstance(value, bool):
            cls.verbose_mode = value
        else:
            raise ValueError

    @classmethod
    def set_debug_mode(cls, value):
        """Set the class variable for debug_mode."""
        if isinstance(value, bool):
            cls.debug_mode = value
        else:
            raise ValueError


def timed(func):
    """Decorator for timing a function.

    Modifies func to return a tuple of:
        (execution time, original func's return value)
    """

    @wraps(func)
    def run_func(*args, **kwargs):
        """Time a function."""
        start = timeit.default_timer()
        result = func(*args, **kwargs)
        end = timeit.default_timer()
        return (end - start, result)

    return run_func


def robo_print(message, log_level=LogLevel.LOG, indent=0):
    """Print the specified message in an appropriate color, and only print
    debug output if debug_mode is True.

    Args:
        log_level: LogLevel property for desired loglevel.
        message: String to be printed to output.
    """
    color = log_level[0] if color_setting else ""
    indents = indent * " "
    if log_level[1]:
        prefix = "[%s] " % log_level[1]
    else:
        prefix = ""
    suffix = ENDC if color_setting else ""

    line = color + indents + prefix + message + suffix

    if log_level in (LogLevel.ERROR, LogLevel.WARNING):
        print_func = _print_stderr
    else:
        print_func = _print_stdout

    if (
        (
            log_level
            in (LogLevel.ERROR, LogLevel.REMINDER, LogLevel.WARNING, LogLevel.LOG)
        )
        or (log_level is LogLevel.DEBUG and OutputMode.debug_mode)
        or (
            log_level is LogLevel.VERBOSE
            and (OutputMode.verbose_mode or OutputMode.debug_mode)
        )
    ):
        for wrapped_line in textwrap.wrap(
            line,
            width=100,  # TODO: Is this optimal? Consider default Terminal.app and iTerm.app settings.
            break_long_words=False,
            break_on_hyphens=False,
            subsequent_indent="    ",
        ):
            print_func(wrapped_line)


def strip_dev_suffix(dev):
    """Removes corporation suffix from developer names, if present."""
    corp_suffixes = (
        "incorporated",
        "corporation",
        "limited",
        "oy/ltd",
        "pty ltd",
        "pty. ltd",
        "pvt ltd",
        "pvt. ltd",
        "s.a r.l",
        "sa rl",
        "sarl",
        "srl",
        "corp",
        "gmbh",
        "l.l.c",
        "inc",
        "llc",
        "ltd",
        "pvt",
        "oy",
        "sa",
        "ab",
    )
    if dev not in (None, ""):
        for suffix in corp_suffixes:
            if dev.lower().rstrip(" .").endswith(suffix):
                dev = dev.rstrip(" .")[: len(dev) - len(suffix) - 1].rstrip(",. ")
                break
    return dev


def recipe_dirpath(app_name, dev, prefs):
    """Returns a macOS-friendly path to use for recipes."""
    # Special characters that shouldn't be in macOS file/folder names.
    char_replacements = (("/", "-"), ("\\", "-"), (":", "-"), ("*", "-"), ("?", ""))
    for char in char_replacements:
        app_name = app_name.replace(char[0], char[1])
    path_components = [prefs["RecipeCreateLocation"]]
    if dev is not None and prefs.get("FollowOfficialJSSRecipesFormat", False) is False:
        # TODO (Elliot): Put this in the preferences.
        if prefs.get("StripDeveloperSuffixes", False) is True:
            dev = strip_dev_suffix(dev)
        for char in char_replacements:
            dev = dev.replace(char[0], char[1])
        path_components.append(dev)
    else:
        path_components.append(app_name)

    return robo_join(*path_components)


def create_dest_dirs(path):
    """Creates the path to the recipe export location, if it doesn't exist. If
    intermediate folders are necessary in order to create the path, they will
    be created too.

    Args:
        path: The path to the directory that needs to be created.
    """
    dest_dir = os.path.expanduser(path)
    if not os.path.exists(dest_dir):
        try:
            os.makedirs(dest_dir)
        except OSError as error:
            raise RoboError("Unable to create directory at %s." % dest_dir, error)


def extract_app_icon(facts, png_path):
    """Convert the app's icns file to 300x300 png at the specified path.
    300x300 is Munki's preferred size, and 128x128 is Jamf Pro's preferred size,
    as of 2015-08-01.

    Args:
        facts: Dictionary with key "icon_path", value: string path to
            icon.
        png_path: The path to the .png file we're creating.
    """
    icon_path = facts["icon_path"]
    png_path_absolute = os.path.expanduser(png_path)
    create_dest_dirs(os.path.dirname(png_path_absolute))

    # Add .icns if the icon path doesn't already end with .icns.
    if not icon_path.endswith(".icns"):
        icon_path = icon_path + ".icns"

    if not os.path.exists(png_path_absolute):
        cmd = (
            '/usr/bin/sips -s format png "%s" --out "%s" '
            "--resampleHeightWidthMax 300" % (icon_path, png_path_absolute)
        )
        exitcode, _, err = get_exitcode_stdout_stderr(cmd)
        if exitcode == 0:
            robo_print("%s" % png_path, LogLevel.VERBOSE, 4)
            facts["icons"].append(png_path)
        else:
            facts["warnings"].append(
                "An error occurred during icon extraction: %s" % err
            )


def get_exitcode_stdout_stderr(cmd):
    """Execute the external command and get its exitcode, stdout and stderr.

    Args:
        cmd: The shell command to be executed.

    Returns:
        exitcode: Zero upon success. Non-zero upon error.
        out: String from standard output.
        err: String from standard error.
    """
    if "|" in cmd:
        raise RoboError(
            "Piped commands are deprecated. Please report this issue:\n"
            "    https://github.com/homebysix/recipe-robot/issues/new\n"
            "Command: {}".format(cmd)
        )
    proc = Popen(shlex.split(cmd), stdout=PIPE, stderr=PIPE)
    out, err = proc.communicate()
    exitcode = proc.returncode

    return exitcode, out, err


def _print_stderr(p):
    print >>sys.stderr, p


def _print_stdout(p):
    print(p)


def print_welcome_text():
    """Print the text that appears when you run Recipe Robot."""
    welcome_text = (
        """
                      -----------------------------------
                     |  Welcome to Recipe Robot v%s.  |
                      -----------------------------------
                                \   _[]_
                                 \  [oo]
                                   d-||-b
                                     ||
                                   _/  \_
    """
        % __version__
    )

    robo_print(welcome_text)


def print_death_text():
    """Print the text that appears when you RoboError out."""
    death_text = """
                                    _[]_
                                    [xx]
                                   q-||-p
                                     ||
                                   _/  \_
    """
    robo_print(death_text, LogLevel.ERROR)


def reset_term_colors():
    """Ensure terminal colors are normal."""
    sys.stdout.write(ENDC)


def write_report(report, report_file):
    FoundationPlist.writePlist(report, report_file)


def get_user_defaults():
    defaults = NSUserDefaults.alloc().initWithSuiteName_(
        "com.elliotjordan.recipe-robot"
    )
    default_dict = defaults.dictionaryRepresentation()
    return default_dict if len(default_dict) else None


def save_user_defaults(prefs):
    defaults = NSUserDefaults.alloc().initWithSuiteName_(
        "com.elliotjordan.recipe-robot"
    )
    for key, value in prefs.iteritems():
        defaults.setValue_forKey_(value, key)


def any_item_in_string(items, test_string):
    """Return true if any item in items is in test_string"""
    return any([True for item in items if item in test_string])


def create_existing_recipe_list(facts):
    """Use autopkg search results to build existing recipe list.

    Args:
        facts: The Facts instance containing all of our information.
            Required keys:
                app_name: The app's name.
                recipes: The recipes to build.
    """
    app_name = facts["app_name"]
    recipes = facts["recipes"]
    # TODO(Elliot): Suggest users create GitHub API token to prevent
    # limiting. (#29)

    # Generate an array to run through `autopkg search`.
    recipe_searches = [quote_plus(app_name)]

    app_name_no_space = quote_plus("".join(app_name.split()))
    if app_name_no_space not in recipe_searches:
        recipe_searches.append(app_name_no_space)

    app_name_no_symbol = quote_plus(re.sub(r"[^\w]", "", app_name))
    if app_name_no_symbol not in recipe_searches:
        recipe_searches.append(app_name_no_symbol)

    for this_search in recipe_searches:
        robo_print(
            "Searching for existing AutoPkg recipes for %s..." % this_search,
            LogLevel.VERBOSE,
        )
        # TODO: Check for token in AutoPkg preferences.
        if os.path.isfile(os.path.expanduser("~/.autopkg_gh_token")):
            robo_print("Using GitHub token file", LogLevel.VERBOSE, 4)
            cmd = (
                "/usr/local/bin/autopkg search --path-only --use-token "
                "%s" % this_search
            )
        else:
            cmd = "/usr/local/bin/autopkg search --path-only %s" % this_search
        exitcode, out, err = get_exitcode_stdout_stderr(cmd)
        out = out.split("\n")
        if exitcode == 0:
            # Set to False by default. If found, set True.
            is_existing = False
            # For each recipe type, see if it exists in the search results.
            for recipe in recipes:
                recipe_name = "%s.%s.recipe" % (this_search, recipe["type"])
                for line in out:
                    if line.lower().startswith(recipe_name.lower()):
                        # An existing recipe was found.
                        if is_existing is False:
                            robo_print("Found existing recipe(s):", LogLevel.LOG, 4)
                            is_existing = True
                            recipe["existing"] = True
                        robo_print(recipe_name, LogLevel.LOG, 8)
                        break
            if is_existing is True:
                raise RoboError(
                    "Sorry, AutoPkg recipes already exist for this app, and "
                    "I can't blend new recipes with existing recipes.\n\nHere "
                    "are my suggestions:\n\t- See if one of the above recipes "
                    "meets your needs, either as-is or using an override."
                    "\n\t- Write your own recipe using one of the above as "
                    "the ParentRecipe.\n\t- Use Recipe Robot to assist in "
                    "the creation of a new child recipe, as seen here:\n\t  "
                    "https://youtu.be/5VKDzY8bBxI?t=2829"
                )
            else:
                robo_print("No results", LogLevel.VERBOSE, 4)
        else:
            raise RoboError(
                "I encountered this error while checking for "
                "existing recipes: {}".format(err)
            )


def congratulate(prefs, first_timer):
    """Display a friendly congratulatory message upon creating recipes.

    Args:
        prefs: A dictionary containing a key/value pair for each
            preference.
    """
    congrats_msg = (
        "Amazing.",
        "Easy peasy.",
        "Fantastic.",
        "Good on ya!",
        "Imagine all the typing you saved.",
        "Isn't meta-automation great?",
        "(Yep, it's pretty fun for me too.)",
        "Pretty cool, right?",
        "Round of applause for you!",
        "Terrific job!",
        "Thanks!",
        "That's awesome!",
        "Want to do another?",
        "Well done!",
        "You rock star, you.",
    )
    if prefs["RecipeCreateCount"] > 0:
        if first_timer:
            if prefs["RecipeCreateCount"] == 1:
                recipe_count = "your first recipe"
            else:
                recipe_count = "your first {} recipes".format(
                    prefs["RecipeCreateCount"]
                )
            congrats = "Congratulations!"
        else:
            if prefs["RecipeCreateCount"] == 1:
                recipe_count = "1 recipe"
            else:
                recipe_count = "{} recipes".format(prefs["RecipeCreateCount"])
            congrats = random_choice(congrats_msg)
        robo_print(
            "\nYou've created {} with Recipe Robot. {}\n".format(recipe_count, congrats)
        )


def robo_join(*args):
    return os.path.expanduser(os.path.join(*args))
