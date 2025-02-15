"""Drop-in replacement for the thread module.

Meant to be used as a brain-dead substitute so that threaded code does
not need to be rewritten for when the thread module is not present.

Suggested usage is::

    try:
        try:
            import _thread  # Python >= 3
        except:
            import thread as _thread  # Python < 3
    except ImportError:
        import _placeholder_thread as _thread

"""
# Exports only things specified by thread documentation;
# skipping obsolete synonyms allocate(), start_new(), exit_thread().
__all__ = ['error', 'start_new_thread', 'exit', 'get_ident', 'allocate_lock',
           'interrupt_main', 'LockType']

# A placeholder value
TIMEOUT_MAX = 2**31

# NOTE: this module can be imported early in the extension building process,
# and so top level imports of other modules should be avoided.  Instead, all
# imports are done when needed on a function-by-function basis.  Since threads
# are disabled, the import lock should not be an issue anyway (??).

class error(Exception):
    """Placeholder implementation of _thread.error."""

    def __init__(self, *args):
        self.args = args

def start_new_thread(function, args, kwargs={}):
    """Placeholder implementation of _thread.start_new_thread().

    Compatibility is maintained by making sure that ``args`` is a
    tuple and ``kwargs`` is a dictionary.  If an exception is raised
    and it is SystemExit (which can be done by _thread.exit()) it is
    caught and nothing is done; all other exceptions are printed out
    by using traceback.print_exc().

    If the executed function calls interrupt_main the KeyboardInterrupt will be
    raised when the function returns.

    """
    if type(args) != type(tuple()):
        raise TypeError("2nd arg must be a tuple")
    if type(kwargs) != type(dict()):
        raise TypeError("3rd arg must be a dict")
    global _main
    _main = False
    try:
        function(*args, **kwargs)
    except SystemExit:
        pass
    except:
        import traceback
        traceback.print_exc()
    _main = True
    global _interrupt
    if _interrupt:
        _interrupt = False
        raise KeyboardInterrupt

def exit():
    """Placeholder implementation of _thread.exit()."""
    raise SystemExit

def get_ident():
    """Placeholder implementation of _thread.get_ident().

    Since this module should only be used when _threadmodule is not
    available, it is safe to assume that the current process is the
    only thread.  Thus a constant can be safely returned.
    """
    return -1

def allocate_lock():
    """Placeholder implementation of _thread.allocate_lock()."""
    return LockType()

def stack_size(size=None):
    """Placeholder implementation of _thread.stack_size()."""
    if size is not None:
        raise error("setting thread stack size not supported")
    return 0

class LockType(object):
    """Class implementing placeholder implementation of _thread.LockType.

    Compatibility is maintained by maintaining self.locked_status
    which is a boolean that stores the state of the lock.  Pickling of
    the lock, though, should not be done since if the _thread module is
    then used with an unpickled ``lock()`` from here problems could
    occur from this class not having atomic methods.

    """

    def __init__(self):
        self.locked_status = False

    def acquire(self, waitflag=None, timeout=-1):
        """Placeholder implementation of acquire().

        For blocking calls, self.locked_status is automatically set to
        True and returned appropriately based on value of
        ``waitflag``.  If it is non-blocking, then the value is
        actually checked and not set if it is already acquired.  This
        is all done so that threading.Condition's assert statements
        aren't triggered and throw a little fit.

        """
        if waitflag is None or waitflag:
            self.locked_status = True
            return True
        else:
            if not self.locked_status:
                self.locked_status = True
                return True
            else:
                if timeout > 0:
                    import time
                    time.sleep(timeout)
                return False

    __enter__ = acquire

    def __exit__(self, typ, val, tb):
        self.release()

    def release(self):
        """Release the placeholder lock."""
        # XXX Perhaps shouldn't actually bother to test?  Could lead
        #     to problems for complex, threaded code.
        if not self.locked_status:
            raise error
        self.locked_status = False
        return True

    def locked(self):
        return self.locked_status

# Used to signal that interrupt_main was called in a "thread"
_interrupt = False
# True when not executing in a "thread"
_main = True

def interrupt_main():
    """Set _interrupt flag to True to have start_new_thread raise
    KeyboardInterrupt upon exiting."""
    if _main:
        raise KeyboardInterrupt
    else:
        global _interrupt
        _interrupt = True
