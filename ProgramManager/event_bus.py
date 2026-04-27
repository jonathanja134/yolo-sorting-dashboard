def _noop_emit(event, data):
    del event, data

_emit_impl = _noop_emit

def configure_emit(emit_fn):
    global _emit_impl
    _emit_impl = emit_fn

def _async_emit(event, data):
    _emit_impl(event, data)
