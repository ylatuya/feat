# F3AT - Flumotion Asynchronous Autonomous Agent Toolkit
# Copyright (C) 2010,2011 Flumotion Services, S.A.
# All rights reserved.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

# See "LICENSE.GPL" in the source distribution for more information.

# Headers in this file shall remain intact.
import re
import StringIO

from twisted.python.failure import Failure

from feat.common import log, decorator, reflect
from feat.extern.log import log as xlog


@decorator.simple_function
def log_errors(function):
    """Logs the exceptions raised by the decorated function
    without interfering. For debugging purpose."""

    def wrapper(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except BaseException as e:
            handle_exception(None, e, "Exception in function %s",
                             reflect.canonical_name(function))
            raise

    return wrapper


@decorator.simple_function
def print_errors(function):
    """Prints the exceptions raised by the decorated function
    without interfering. For debugging purpose."""

    def wrapper(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except BaseException as e:
            print ("Exception raise calling %s: %s"
                   % (reflect.canonical_name(function),
                      get_exception_message(e)))
            raise

    return wrapper


class FeatError(Exception):
    """
    An exception that keep information on the cause of its creation.
    The cause may be other exception or a Failure.
    """

    default_error_code = None
    default_error_name = None

    def __init__(self, *args, **kwargs):
        self.data = kwargs.pop('data', None)
        self.cause = kwargs.pop('cause', None)
        default_code = self.default_error_code
        default_name = self.default_error_name or self.__class__.__name__
        self.error_code = kwargs.pop('code', default_code)
        self.error_name = kwargs.pop('name', default_name)

        Exception.__init__(self, *args, **kwargs)

        self.cause_details = None
        self.cause_traceback = None

        if self.cause:
            if isinstance(self.cause, Exception):
                self.cause_details = get_exception_message(self.cause)
            elif isinstance(self.cause, Failure):
                self.causeDetails = get_failure_message(self.cause)
            else:
                self.causeDetails = "Unknown"

            if isinstance(self.cause, Failure):
                f = self.cause
                self.cause = f.value
                try:
                    self.cause_traceback = f.getTraceback()
                except:
                    # Ignore failure.NoCurrentExceptionError
                    pass
            else:
                try:
                    f = Failure()
                    if f.value == self.cause:
                        self.cause_traceback = f.getTraceback()
                except:
                    # Ignore failure.NoCurrentExceptionError
                    pass


def get_exception_message(exception):
    try:
        msg = xlog.getExceptionMessage(exception)
    except IndexError:
        # log.getExceptionMessage do not like exceptions without messages ?
        msg = ""
    if isinstance(exception, FeatError):
        details = exception.cause_details
        if details:
            msg += "; CAUSED BY " + details
    return msg


def get_failure_message(failure):
    try:
        msg = xlog.getFailureMessage(failure)
    except KeyError:
        # Sometime happen for strange error, just when we relly need a message
        msg = failure.getErrorMessage()
    exception = failure.value
    if isinstance(exception, FeatError):
        details = exception.cause_details
        if details:
            msg += "; CAUSED BY " + details
    return msg


def get_exception_traceback(exception=None, cleanup=False):
    #FIXME: Only work if the exception was raised in the current context
    f = Failure(exception)

    if exception and (f.value != exception):
        return "Not Traceback information available"

    io = StringIO.StringIO()
    tb = f.getTraceback()
    if cleanup:
        tb = clean_traceback(tb)
    print >> io, tb

    if isinstance(f.value, FeatError):
        if f.value.cause_traceback:
            print >> io, "\n\nCAUSED BY:\n\n"
            tb = f.value.cause_traceback
            if cleanup:
                tb = clean_traceback(tb)
            print >> io, tb

    return io.getvalue()


def get_failure_traceback(failure, cleanup=False):
    if isinstance(failure.type, str):
        return ""

    io = StringIO.StringIO()
    tb = failure.getTraceback()
    if cleanup:
        tb = clean_traceback(tb)
    print >> io, tb
    exception = failure.value
    if exception and isinstance(exception, FeatError):
        if exception.cause_traceback:
            print >> io, "\n\nCAUSED BY:\n\n"
            tb = exception.cause_traceback
            if cleanup:
                tb = clean_traceback(tb)
            print >> io, tb

    return io.getvalue()


def clean_traceback(tb):
    prefix = __file__[:__file__.find("feat/common/error.py")]
    regex = re.compile("(\s*File\s*\")(%s)([a-zA-Z-_\. \\/]*)(\".*)"
                       % prefix.replace("\\", "\\\\"))

    def cleanup(line):
        m = regex.match(line)
        if m:
            return m.group(1) + ".../" + m.group(3) + m.group(4)
        else:
            return line

    return '\n'.join(map(cleanup, tb.split('\n')))


def handle_failure(source, failure, template, *args, **kwargs):
    logger = _get_logger(source)

    info = kwargs.get("info", None)
    debug = kwargs.get("debug", None)
    msg = get_failure_message(failure)

    category = logger.log_category
    if category is None:
        category = 'feat'
    if xlog.getCategoryLevel(category) in [xlog.LOG, xlog.DEBUG]:
        cleanup = kwargs.get("clean_traceback", False)
        tb = get_failure_traceback(failure, cleanup)
        logger.error(template + ": %s\n%s", *(args + (msg, tb)))
    else:
        logger.error(template + ": %s", *(args + (msg, )))

    if log.verbose:
        if info:
            logger.info("Additional Information:\n%s", info)
        if debug:
            logger.debug("Additional Debug:\n%s", debug)


def handle_exception(source, exception, template, *args, **kwargs):
    logger = _get_logger(source)

    info = kwargs.get("info", None)
    debug = kwargs.get("debug", None)
    msg = get_exception_message(exception)

    category = logger.log_category
    if category is None:
        category = 'feat'
    if xlog.getCategoryLevel(category) in [xlog.LOG, xlog.DEBUG]:
        cleanup = kwargs.get("clean_traceback", False)
        tb = get_exception_traceback(exception, cleanup)
        logger.error(template + ": %s\n%s", *(args + (msg, tb)))
    else:
        logger.error(template + ": %s", *(args + (msg, )))

    if log.verbose:
        if info:
            logger.info("Additional Information:\n%s", debug)
        if debug:
            logger.debug("Additional Debug:\n%s", debug)


### private ###


def _get_logger(maybe_logger):
    if maybe_logger is None or not log.ILogger.providedBy(maybe_logger):
        return log.create_logger()
    return log.ILogger(maybe_logger)
