#default function used before connection SocketIO preventing errors
def _noop_emit(event, data):
    del event, data
#sender function holder default _noop_emit
_emit_impl = _noop_emit

#configure emit change the function holder from _noop_emit to emit_fn for normal operation
def configure_emit(emit_fn):
    global _emit_impl
    _emit_impl = emit_fn

#standard messager called when normal operation must be send  
def _async_emit(event, data):
    _emit_impl(event, data)
