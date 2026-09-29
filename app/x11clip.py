"""Read the X11 CLIPBOARD as raw bytes via libX11 (ctypes, no extra packages).

Tk's own `clipboard get` stops at the first NUL on X11, so a log copied from
an app that keeps NULs (Qt viewers, editors) arrives cut off before Python
ever sees it. Asking the owner for the selection ourselves keeps every byte.
Returns None whenever this path isn't usable; callers fall back to Tk.
"""
import ctypes
import ctypes.util
import time

_SELECTION_NOTIFY = 31
_PROPERTY_NOTIFY = 28
_PROPERTY_NEW_VALUE = 0
_PROPERTY_CHANGE_MASK = 1 << 22
_CHUNK_LONGS = 1 << 22  # XGetWindowProperty length is in 32-bit units → 16 MB per read


class _XSelectionEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p), ("requestor", ctypes.c_ulong), ("selection", ctypes.c_ulong),
        ("target", ctypes.c_ulong), ("property", ctypes.c_ulong), ("time", ctypes.c_ulong),
    ]


class _XPropertyEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p), ("window", ctypes.c_ulong), ("atom", ctypes.c_ulong),
        ("time", ctypes.c_ulong), ("state", ctypes.c_int),
    ]


class _XEvent(ctypes.Union):
    _fields_ = [
        ("type", ctypes.c_int), ("xselection", _XSelectionEvent),
        ("xproperty", _XPropertyEvent), ("pad", ctypes.c_long * 24),
    ]


def _load_xlib():
    x = ctypes.cdll.LoadLibrary(ctypes.util.find_library("X11") or "libX11.so.6")
    ul, vp, i = ctypes.c_ulong, ctypes.c_void_p, ctypes.c_int
    x.XOpenDisplay.restype, x.XOpenDisplay.argtypes = vp, [ctypes.c_char_p]
    x.XDefaultRootWindow.restype, x.XDefaultRootWindow.argtypes = ul, [vp]
    x.XCreateSimpleWindow.restype = ul
    x.XCreateSimpleWindow.argtypes = [vp, ul, i, i, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ul, ul]
    x.XInternAtom.restype, x.XInternAtom.argtypes = ul, [vp, ctypes.c_char_p, i]
    x.XGetSelectionOwner.restype, x.XGetSelectionOwner.argtypes = ul, [vp, ul]
    x.XSelectInput.argtypes = [vp, ul, ctypes.c_long]
    x.XConvertSelection.argtypes = [vp, ul, ul, ul, ul, ul]
    x.XFlush.argtypes = [vp]
    x.XPending.argtypes = [vp]
    x.XNextEvent.argtypes = [vp, ctypes.POINTER(_XEvent)]
    x.XGetWindowProperty.argtypes = [
        vp, ul, ul, ctypes.c_long, ctypes.c_long, i, ul,
        ctypes.POINTER(ul), ctypes.POINTER(i), ctypes.POINTER(ul), ctypes.POINTER(ul),
        ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
    ]
    x.XFree.argtypes = [vp]
    x.XDestroyWindow.argtypes = [vp, ul]
    x.XCloseDisplay.argtypes = [vp]
    return x


def _wait(x, dpy, ev, want, deadline):
    while time.monotonic() < deadline:
        while x.XPending(dpy):
            x.XNextEvent(dpy, ctypes.byref(ev))
            if want(ev):
                return True
        time.sleep(0.005)
    return False


def _read_prop(x, dpy, win, prop):
    """Read and delete a property. Returns (type_atom, bytes)."""
    out, offset, ptype = bytearray(), 0, 0
    while True:
        atype, afmt = ctypes.c_ulong(), ctypes.c_int()
        nitems, after = ctypes.c_ulong(), ctypes.c_ulong()
        data = ctypes.POINTER(ctypes.c_ubyte)()
        rc = x.XGetWindowProperty(dpy, win, prop, offset, _CHUNK_LONGS, 0, 0,
                                  ctypes.byref(atype), ctypes.byref(afmt),
                                  ctypes.byref(nitems), ctypes.byref(after), ctypes.byref(data))
        if rc != 0:
            raise OSError("XGetWindowProperty failed")
        ptype = atype.value
        unit = {8: 1, 16: ctypes.sizeof(ctypes.c_short), 32: ctypes.sizeof(ctypes.c_long)}.get(afmt.value, 1)
        if data:
            out += ctypes.string_at(data, nitems.value * unit)
            x.XFree(data)
        if not after.value:
            break
        offset += nitems.value * unit // 4
    x.XGetWindowProperty(dpy, win, prop, 0, 0, 1, 0, ctypes.byref(ctypes.c_ulong()),
                         ctypes.byref(ctypes.c_int()), ctypes.byref(ctypes.c_ulong()),
                         ctypes.byref(ctypes.c_ulong()), ctypes.byref(ctypes.POINTER(ctypes.c_ubyte)()))
    return ptype, bytes(out)


def read_clipboard(selection: str = "CLIPBOARD", timeout: float = 3.0) -> str | None:
    try:
        x = _load_xlib()
    except OSError:
        return None
    dpy = x.XOpenDisplay(None)
    if not dpy:
        return None
    win = 0
    try:
        atom = lambda name: x.XInternAtom(dpy, name.encode(), 0)
        sel, incr, prop = atom(selection), atom("INCR"), atom("QRTRANS_CLIP")
        if not x.XGetSelectionOwner(dpy, sel):
            return None
        win = x.XCreateSimpleWindow(dpy, x.XDefaultRootWindow(dpy), 0, 0, 1, 1, 0, 0, 0)
        x.XSelectInput(dpy, win, _PROPERTY_CHANGE_MASK)
        ev = _XEvent()
        for target, encoding in (("UTF8_STRING", "utf-8"), ("STRING", "latin-1")):
            x.XConvertSelection(dpy, sel, atom(target), prop, win, 0)
            x.XFlush(dpy)
            deadline = time.monotonic() + timeout
            if not _wait(x, dpy, ev, lambda e: e.type == _SELECTION_NOTIFY, deadline):
                return None
            if ev.xselection.property == 0:  # owner refused this target
                continue
            ptype, data = _read_prop(x, dpy, win, prop)
            if ptype == incr:  # large transfer: owner sends chunks, empty chunk ends it
                data = bytearray()
                while True:
                    deadline = time.monotonic() + timeout
                    if not _wait(x, dpy, ev, lambda e: e.type == _PROPERTY_NOTIFY
                                 and e.xproperty.atom == prop
                                 and e.xproperty.state == _PROPERTY_NEW_VALUE, deadline):
                        return None
                    _, chunk = _read_prop(x, dpy, win, prop)
                    if not chunk:
                        break
                    data += chunk
            return bytes(data).decode(encoding, errors="replace")
        return None
    except Exception:
        return None
    finally:
        if win:
            x.XDestroyWindow(dpy, win)
        x.XCloseDisplay(dpy)
